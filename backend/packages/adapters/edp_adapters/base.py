from dataclasses import dataclass


@dataclass
class SourceRecord:
    """上游系统单条记录的传输载体（W1 骨架，字段随 W2 EDP-010 补齐）。"""
