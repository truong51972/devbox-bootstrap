"""Native provider adapters for semantic results.

Prefer explicit native formats; parse documented command columns only at
the provider boundary. Unknown/unsupported output is never guessed.
"""
import csv
import json
import os
from pathlib import Path
import platform
import re
import shutil

from . import agents, data, environment, health, network, system
from .native import native, local_docker, bytes_label
from .results import Cell, Metric, ResourceData, Result, TextData, table, report

def _json(raw):
    return json.loads(raw) if raw != "(no output)" else []

def _csv(raw):
    return list(csv.reader(raw.splitlines(), skipinitialspace=True)) if raw != "(no output)" else []

def _lines(raw):
    return [] if raw == "(no output)" else raw.splitlines()

def _ports(key, value):
    cmd = ["ss", "-H", "-lntup"]
    if key == "net.port":
        cmd += ["sport", "=", ":" + str(network.port_number(value))]
    raw = native(cmd)
    rows = []
    for line in _lines(raw):
        parts = line.split(None, 6)
        if len(parts) < 6:
            continue
        proto, state, _, _, local, peer = parts[:6]
        owner = parts[6] if len(parts) > 6 else ""
        # Multiple owners are possible; display all visible PID/name pairs.
        matches = re.findall(r'\("([^"]+)",pid=(\d+)', owner)
        addr, _, port = local.rpartition(":")
        rows.append((port, proto, addr, state, ", ".join(n for n, _ in matches) or "Unknown",
                     ", ".join(p for _, p in matches) or "Unknown"))
    return table(("Port", "Protocol", "Address", "State", "Process", "PID"), rows,
                 f"{len(rows)} local listeners", raw, ("Process owners may be hidden by permissions.",))

def _network(key, value, cwd):
    if key in ("net.ports", "net.port"):
        return _ports(key, value)
    if key == "net.ip":
        raw = native(["ip", "-j", "address"])
        rows = [(r.get("ifname", "?"), r.get("operstate", "UNKNOWN"),
                 ", ".join(a.get("local", "?") + "/" + str(a.get("prefixlen", "?")) for a in r.get("addr_info", [])))
                for r in _json(raw)]
        return table(("Interface", "State", "Addresses"), rows, f"{len(rows)} interfaces", raw)
    if key == "net.routes":
        raw = native(["ip", "-j", "route"])
        rows = [(r.get("dst", "default"), r.get("gateway", "—"), r.get("dev", "—"), r.get("metric", "—")) for r in _json(raw)]
        return table(("Destination", "Gateway", "Interface", "Metric"), rows, f"{len(rows)} routes", raw)
    if key == "net.dns":
        raw = network.dns(value, cwd)
        rows = []
        seen = set()
        for line in _lines(raw):
            p = line.split(None, 2)
            if p and p[0] not in seen:
                seen.add(p[0])
                rows.append((p[0], p[2] if len(p) > 2 else value))
        return table(("Address", "Name"), rows, f"{len(rows)} resolved addresses", raw)
    if key == "net.http":
        raw = network.http(value, cwd)
        parts = dict(line.split(" ", 1) for line in _lines(raw) if " " in line)
        code = int(parts["HTTP"])
        tone = "installed" if 200 <= code < 300 else "warning" if 300 <= code < 400 else "error"
        summary = "Successful HTTP response" if 200 <= code < 300 else "Redirect response" if 300 <= code < 400 else "HTTP error response"
        if code == 0:
            summary = "No HTTP response"
        return report((("HTTP status", Cell(str(code), tone)), ("Method", "HEAD"), ("Remote IP", parts.get("Remote", "Unknown")),
                       ("Duration", parts.get("Total", "Unknown")), ("Redirects", "Not followed")), summary, raw, tone,
                      ("HEAD status does not verify application health.",))
    if key == "net.tcp":
        raw = network.tcp(value, cwd)
        return report((("Connection", Cell("Connected", "installed")), ("Evidence", raw)), "TCP connection accepted", raw)
    raw = network.tls(value, cwd)
    return report(tuple(line.split(": ", 1) for line in _lines(raw) if ": " in line), "Verified TLS connection", raw)

def _system(key, value, cwd):
    if key == "sys.host":
        raw = system.host(value, cwd)
        return report(tuple(line.split(": ", 1) for line in _lines(raw) if ": " in line), "Host snapshot", raw)
    if key == "sys.processes":
        raw = system.processes(value, cwd)
        rows = [tuple(line.split(None, 4)) for line in _lines(raw)[1:]]
        return table(("PID", "User", "CPU %", "RAM %", "Process"), [r for r in rows if len(r) == 5], f"{len(rows)} matching processes", raw)
    if key in ("sys.gpu", "sys.gpu-processes"):
        raw = system.gpu(value, cwd) if key == "sys.gpu" else system.gpu_processes(value, cwd)
        rows = _csv(raw)
        if key == "sys.gpu-processes":
            return table(("PID", "Process", "VRAM"), [r for r in rows[1:] if len(r) == 3], f"{max(0,len(rows)-1)} compute processes", raw)
        metrics = []
        def number(s):
            try:
                return float(s.split()[0])
            except (ValueError, IndexError):
                return None
        for row in rows[1:]:
            if len(row) != 6:
                continue
            idx, name, total, used, util, temp = row
            t, u, load = number(total), number(used), number(util)
            metrics.extend((Metric(f"GPU {idx} · {name}", f"{temp} °C"),
                            Metric("VRAM", f"{used} / {total}", u/t if u is not None and t else None),
                            Metric("Utilization", util, load/100 if load is not None else None)))
        return Result(ResourceData(tuple(metrics)), "GPU snapshot", raw)
    if key == "sys.services":
        raw = system.services(value, cwd)
        rows = []
        for line in _lines(raw):
            p = line.split(None, 4)
            if len(p) >= 4:
                rows.append((p[0], p[1], Cell(p[2], "installed" if p[2] == "active" else "error" if p[2] == "failed" else "muted"), p[3], p[4] if len(p) > 4 else ""))
        return table(("Unit", "Load", "Active", "Substate", "Description"), rows, f"{len(rows)} loaded services", raw)
    if key == "sys.ssh-agent":
        raw = system.ssh_agent(value, cwd)
        rows = [line.split(None, 2) for line in _lines(raw)]
        return table(("Bits", "Fingerprint", "Identity"), [r for r in rows if len(r) == 3], "Loaded SSH identities", raw)
    if key == "sys.ssh-keys":
        raw = system.ssh_keys(value, cwd)
        rows = [(line,) for line in _lines(raw) if line.endswith(".pub")]
        return table(("Public key path",), rows, f"{len(rows)} public keys", raw)
    raw = system.path_entries(value, cwd)
    return table(("Path",), [(line,) for line in _lines(raw) if line != "Executable not found."], "Executable matches" if value else "PATH entries", raw)

def _storage(key, value, cwd):
    if key == "storage.usage":
        metrics = []
        for path in dict.fromkeys((Path("/"), Path.home())):
            usage = shutil.disk_usage(path)
            metrics.append(Metric(str(path), f"{bytes_label(usage.used)} / {bytes_label(usage.total)}", usage.used / max(1, usage.total)))
        return Result(ResourceData(tuple(metrics)), "Filesystem usage", notes=("Root and home may refer to the same filesystem; do not sum.",))
    if key == "storage.caches":
        return table(("Cache", "State", "Path"), [(name, Cell("Present" if path.is_dir() else "Not found", "installed" if path.is_dir() else "muted"), str(path)) for name, path in system.cache_locations()], "Known cache locations", notes=("No data is deleted.",))
    if key == "storage.cache-sizes":
        raw = system.cache_sizes(value, cwd)
        rows = []
        for line in _lines(raw):
            name, rest = line[:14].strip(), line[14:].strip()
            if name in {n for n, _ in system.cache_locations()}:
                size, _, path = rest.partition("  ")
                rows.append((name, size.strip(), path.strip()))
        return table(("Cache", "Size", "Path"), rows, "Cache footprints", raw, ("Footprints may overlap.",))
    raw = system.largest(value, cwd) if key == "storage.largest" else system.largest_files(value, cwd)
    rows = []
    for line in _lines(raw):
        m = re.match(r"^\s*([\d,.]+\s+[KMGTPE]?i?B)\s{2,}(.*)$", line)
        if m:
            rows.append(m.groups())
    partial = "Partial results:" in raw or "[Output truncated]" in raw
    return table(("Size", "Path"), rows, f"{len(rows)} largest entries", raw, ("Scoped read-only scan; inaccessible paths may be omitted.",), partial)

def _docker(key, value, cwd):
    if key == "docker.logs":
        raw = system.container_logs(value, cwd)
        return Result(TextData(raw, "log"), "Last 100 log lines", raw, notes=("May contain secrets; not persisted.",))
    if key == "docker.ps":
        raw = local_docker(["ps", "-a", "--no-trunc", "--format", "{{json .}}"], cwd)
        rows = []
        for line in _lines(raw):
            r = json.loads(line)
            state = r.get("State", "")
            rows.append((r.get("ID", ""), r.get("Names", ""), Cell(state, "installed" if state == "running" else "warning" if state in ("restarting", "dead", "exited") else "muted"), r.get("Ports", "")))
        return table(("ID", "Name", "State", "Ports"), rows, f"{len(rows)} local containers", raw)
    if key == "docker.compose":
        raw = local_docker(["compose", "ps", "-a", "--format", "json"], cwd)
        try:
            records = _json(raw)
        except ValueError:
            records = [json.loads(line) for line in _lines(raw)]
        if isinstance(records, dict):
            records = [records]
        return table(("Service", "Name", "State", "Health"), [(r.get("Service", ""), r.get("Name", ""), r.get("State", ""), r.get("Health", "")) for r in records], f"{len(records)} Compose containers", raw)
    raw = local_docker(["system", "df", "--format", "{{json .}}"], cwd)
    rows = [json.loads(line) for line in _lines(raw)]
    return table(("Type", "Total", "Active", "Size", "Reclaimable"), [(r.get("Type", ""), r.get("TotalCount", ""), r.get("Active", ""), r.get("Size", ""), r.get("Reclaimable", "")) for r in rows], "Docker disk usage", raw, ("Estimates may overlap.",))

def collect(key, value, cwd):
    """Return None for intentional document/scalar outputs handled by caller."""
    if key.startswith("net."):
        return _network(key, value, cwd)
    if key.startswith("sys.") and key != "sys.terminate":
        return _system(key, value, cwd)
    if key.startswith("storage."):
        return _storage(key, value, cwd)
    if key in ("docker.ps", "docker.compose", "docker.disk", "docker.logs"):
        return _docker(key, value, cwd)
    if key == "health.check":
        rows = health.collect()
        return table(("Check", "State", "Evidence", "Recommendation"),
                     [(r["label"], Cell(r["status"], {"Passed":"installed","Warning":"warning","Unavailable":"muted"}.get(r["status"],"error")), r["evidence"], r.get("recommendation", "—")) for r in rows],
                     f"{sum(r['status']=='Passed' for r in rows)}/{len(rows)} checks passed", json.dumps(rows, indent=2))
    if key == "agent.list":
        from tui.agent_status import AGENTS, LABELS
        rows = []
        for a in AGENTS:
            path = shutil.which(a)
            rows.append((LABELS[a], a, Cell("Available" if path else "Unavailable", "installed" if path else "muted"), path or "—"))
        return table(("Agent", "Agent ID", "CLI", "Executable"), rows, "Coding agent discovery")
    if key == "project.detect":
        path = Path(cwd)
        rows = [(name,) for name in system.PROJECT_MARKERS if (path / name).exists()]
        return table(("Detected marker",), rows, str(path), notes=("Project scripts are not executed.",))
    if key == "agent.version":
        raw = agents.version(value, cwd)
        return report((("Agent", value), ("Reported version", raw)), "Agent version", raw)
    if key in ("agent.skills", "agent.skill-updates"):
        raw = agents.skills(value, cwd) if key == "agent.skills" else agents.skill_updates(value, cwd)
        return Result(TextData(raw, "text"), "Skills CLI report", raw, notes=("Native report; no changes applied.",))
    if key == "env.profile":
        raw = environment.profile_plan(value, cwd)
        return Result(TextData(raw), "Desired-state preview", raw, tone="warning", notes=("No changes applied.",))
    if key == "project.git":
        raw = system.git_status(value, cwd)
        lines = _lines(raw)
        branch = next((line[3:] for line in lines if line.startswith("## ")), "Unknown")
        rows = [(line[:2], line[3:]) for line in lines if not line.startswith("## ") and len(line) >= 3]
        return table(("State", "Tracked path"), rows, "Branch: " + branch, raw, ("Untracked files are excluded.",))
    if key == "health.json":
        raw = health.report_json(value, cwd)
        return Result(TextData(raw, "json"), "Diagnostic JSON", raw)
    return None
