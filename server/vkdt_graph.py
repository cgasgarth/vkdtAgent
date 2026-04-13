from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ModuleLine:
    name: str
    instance: str
    x: int | None = None
    y: int | None = None


@dataclass(slots=True)
class ConnectionLine:
    src_module: str
    src_instance: str
    src_connector: str
    dst_module: str
    dst_instance: str
    dst_connector: str


@dataclass(slots=True)
class ParamLine:
    module: str
    instance: str
    param: str
    values: list[str]


class VkdtGraph:
    def __init__(
        self,
        *,
        modules: list[ModuleLine] | None = None,
        connections: list[ConnectionLine] | None = None,
        params: list[ParamLine] | None = None,
        extras: list[str] | None = None,
    ) -> None:
        self.modules = modules or []
        self.connections = connections or []
        self.params = params or []
        self.extras = extras or []

    @classmethod
    def parse(cls, text: str) -> "VkdtGraph":
        modules: list[ModuleLine] = []
        connections: list[ConnectionLine] = []
        params: list[ParamLine] = []
        extras: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                extras.append(raw_line)
                continue
            parts = line.split(":")
            tag = parts[0]
            if tag == "module" and len(parts) >= 3:
                x = int(parts[3]) if len(parts) > 3 and parts[3] else None
                y = int(parts[4]) if len(parts) > 4 and parts[4] else None
                modules.append(ModuleLine(parts[1], parts[2], x=x, y=y))
            elif tag == "connect" and len(parts) == 7:
                connections.append(
                    ConnectionLine(
                        parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
                    )
                )
            elif tag == "param" and len(parts) >= 5:
                params.append(ParamLine(parts[1], parts[2], parts[3], parts[4:]))
            else:
                extras.append(raw_line)
        return cls(
            modules=modules, connections=connections, params=params, extras=extras
        )

    @classmethod
    def default_for_image(cls, image_path: str) -> "VkdtGraph":
        graph = cls.parse(
            "\n".join(
                [
                    "module:i-raw:main:43:400",
                    "module:denoise:01:218:400",
                    "module:hilite:01:393:400",
                    "module:demosaic:01:568:400",
                    "module:crop:01:743:400",
                    "module:colour:01:931:400",
                    "module:filmcurv:01:1094:400",
                    "module:llap:01:1269:400",
                    "module:hist:01:1418:634",
                    "module:display:main:1545:400",
                    "module:display:hist:1600:634",
                    "connect:i-raw:main:output:denoise:01:input",
                    "connect:denoise:01:output:hilite:01:input",
                    "connect:hilite:01:output:demosaic:01:input",
                    "connect:demosaic:01:output:crop:01:input",
                    "connect:crop:01:output:colour:01:input",
                    "connect:colour:01:output:filmcurv:01:input",
                    "connect:filmcurv:01:output:llap:01:input",
                    "connect:llap:01:output:display:main:input",
                    "connect:llap:01:output:hist:01:input",
                    "connect:hist:01:output:display:hist:input",
                    "param:colour:01:exposure:0",
                    "param:llap:01:sigma:0.12",
                    "param:llap:01:shadows:1",
                    "param:llap:01:hilights:1",
                    "param:llap:01:clarity:0.2",
                ]
            )
        )
        graph.set_param("i-raw", "main", "filename", [image_path])
        return graph

    def to_text(self) -> str:
        lines: list[str] = []
        for extra in self.extras:
            lines.append(extra)
        for module in self.modules:
            line = f"module:{module.name}:{module.instance}"
            if module.x is not None and module.y is not None:
                line += f":{module.x}:{module.y}"
            lines.append(line)
        for connection in self.connections:
            lines.append(
                ":".join(
                    [
                        "connect",
                        connection.src_module,
                        connection.src_instance,
                        connection.src_connector,
                        connection.dst_module,
                        connection.dst_instance,
                        connection.dst_connector,
                    ]
                )
            )
        for param in self.params:
            lines.append(
                ":".join(
                    ["param", param.module, param.instance, param.param, *param.values]
                )
            )
        return "\n".join(line for line in lines if line is not None).strip() + "\n"

    def write(self, path: Path) -> None:
        path.write_text(self.to_text())

    def module_exists(self, module: str, instance: str) -> bool:
        return any(m.name == module and m.instance == instance for m in self.modules)

    def add_module(
        self, module: str, instance: str, *, x: int | None = None, y: int | None = None
    ) -> None:
        if self.module_exists(module, instance):
            return
        self.modules.append(ModuleLine(module, instance, x=x, y=y))

    def remove_module(self, module: str, instance: str) -> None:
        self.modules = [
            m for m in self.modules if (m.name, m.instance) != (module, instance)
        ]
        self.params = [
            p for p in self.params if (p.module, p.instance) != (module, instance)
        ]
        self.connections = [
            c
            for c in self.connections
            if (c.src_module, c.src_instance) != (module, instance)
            and (c.dst_module, c.dst_instance) != (module, instance)
        ]

    def set_param(
        self,
        module: str,
        instance: str,
        param: str,
        values: list[str | int | float | bool],
    ) -> None:
        value_parts = [
            str(value).lower() if isinstance(value, bool) else str(value)
            for value in values
        ]
        for existing in self.params:
            if (
                existing.module == module
                and existing.instance == instance
                and existing.param == param
            ):
                existing.values = value_parts
                return
        self.params.append(ParamLine(module, instance, param, value_parts))

    def connect(
        self,
        src_module: str,
        src_instance: str,
        src_connector: str,
        dst_module: str,
        dst_instance: str,
        dst_connector: str,
    ) -> None:
        candidate = (
            src_module,
            src_instance,
            src_connector,
            dst_module,
            dst_instance,
            dst_connector,
        )
        for connection in self.connections:
            current = (
                connection.src_module,
                connection.src_instance,
                connection.src_connector,
                connection.dst_module,
                connection.dst_instance,
                connection.dst_connector,
            )
            if current == candidate:
                return
        self.connections.append(
            ConnectionLine(
                src_module,
                src_instance,
                src_connector,
                dst_module,
                dst_instance,
                dst_connector,
            )
        )

    def disconnect(
        self,
        src_module: str,
        src_instance: str,
        src_connector: str,
        dst_module: str,
        dst_instance: str,
        dst_connector: str,
    ) -> None:
        self.connections = [
            c
            for c in self.connections
            if (
                c.src_module,
                c.src_instance,
                c.src_connector,
                c.dst_module,
                c.dst_instance,
                c.dst_connector,
            )
            != (
                src_module,
                src_instance,
                src_connector,
                dst_module,
                dst_instance,
                dst_connector,
            )
        ]

    def insert_module_after(
        self,
        module: str,
        instance: str,
        *,
        after_module: str,
        after_instance: str,
        input_connector: str = "input",
        output_connector: str = "output",
    ) -> None:
        self.add_module(module, instance)
        downstream = [
            c
            for c in self.connections
            if c.src_module == after_module and c.src_instance == after_instance
        ]
        self.connections = [
            c
            for c in self.connections
            if not (c.src_module == after_module and c.src_instance == after_instance)
        ]
        self.connect(
            after_module,
            after_instance,
            output_connector,
            module,
            instance,
            input_connector,
        )
        for edge in downstream:
            self.connect(
                module,
                instance,
                output_connector,
                edge.dst_module,
                edge.dst_instance,
                edge.dst_connector,
            )

    def validate(self) -> list[str]:
        module_keys = {(module.name, module.instance) for module in self.modules}
        errors: list[str] = []
        for connection in self.connections:
            if (connection.src_module, connection.src_instance) not in module_keys:
                errors.append(
                    "missing source module "
                    f"{connection.src_module}:{connection.src_instance}"
                )
            if (connection.dst_module, connection.dst_instance) not in module_keys:
                errors.append(
                    "missing destination module "
                    f"{connection.dst_module}:{connection.dst_instance}"
                )
        return errors

    def summary(self) -> dict[str, object]:
        module_order = [f"{module.name}:{module.instance}" for module in self.modules]
        modules: list[dict[str, object]] = []
        for module in self.modules:
            params = {
                param.param: list(param.values)
                for param in self.params
                if param.module == module.name and param.instance == module.instance
            }
            modules.append(
                {
                    "module": module.name,
                    "instance": module.instance,
                    "params": params,
                }
            )
        connections = [
            {
                "srcModule": connection.src_module,
                "srcInstance": connection.src_instance,
                "srcConnector": connection.src_connector,
                "dstModule": connection.dst_module,
                "dstInstance": connection.dst_instance,
                "dstConnector": connection.dst_connector,
            }
            for connection in self.connections
        ]
        return {
            "moduleOrder": module_order,
            "modules": modules,
            "connections": connections,
        }
