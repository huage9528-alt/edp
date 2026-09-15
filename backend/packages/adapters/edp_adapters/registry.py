class AdapterRegistry:
    """适配器注册表骨架（W1 空 dict，注册/发现协议随 W2 EDP-010 定义）。"""

    def __init__(self) -> None:
        self._adapters: dict[str, object] = {}
