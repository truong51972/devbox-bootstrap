# kubectl and optional Minikube

**Script:** `installers/k8s.sh`

**Official sources:** kubectl docs: https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/ ; Minikube: https://minikube.sigs.k8s.io/docs/start/

**What it does:** Fetch amd64/arm64 kubectl with SHA-256 validation. Minikube is an additional explicit prompt.

**Verification:**

```bash
kubectl version --client
minikube version
```

**Notes and safety:** Use --kubectl-version v1.X.Y to pin the client, within one minor version of your control plane. Existing kubectl installations are preserved unless replacement is explicitly confirmed.

**Rollback:** The bootstrap does not uninstall packages or delete previous user configuration. Use the relevant upstream documentation to remove packages safely; for shell settings, restore the timestamped `.devbox-backup-*` created before edits.
