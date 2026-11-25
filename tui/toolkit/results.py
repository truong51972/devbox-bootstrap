"""Typed result data for presentation; raw documents remain explicit."""
from dataclasses import dataclass
from typing import Union

@dataclass(frozen=True)
class Cell:
    value: str
    tone: str = "body"

@dataclass(frozen=True)
class TableData:
    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]

@dataclass(frozen=True)
class ReportData:
    fields: tuple[tuple[str, Cell], ...]

@dataclass(frozen=True)
class Metric:
    name: str
    value: str
    ratio: float | None = None

@dataclass(frozen=True)
class ResourceData:
    metrics: tuple[Metric, ...]

@dataclass(frozen=True)
class TextData:
    text: str
    language: str = "text"

@dataclass(frozen=True)
class Result:
    data: Union[TableData, ReportData, ResourceData, TextData]
    summary: str
    raw: str = ""
    tone: str = "installed"
    notes: tuple[str, ...] = ()
    partial: bool = False

def table(columns, rows, summary="", raw="", notes=(), partial=False):
    return Result(TableData(tuple(columns), tuple(tuple(c if isinstance(c, Cell) else Cell(str(c)) for c in row) for row in rows)),
                  summary, raw, notes=tuple(notes), partial=partial)

def report(fields, summary="", raw="", tone="installed", notes=()):
    return Result(ReportData(tuple((k, v if isinstance(v, Cell) else Cell(str(v))) for k, v in fields)), summary, raw, tone, tuple(notes))
