from __future__ import annotations

from server.vkdt_graph import VkdtGraph


def test_default_graph_anchors_image_path() -> None:
    graph = VkdtGraph.default_for_image("/tmp/input.raw")
    text = graph.to_text()
    assert "module:i-raw:main" in text
    assert "param:i-raw:main:filename:/tmp/input.raw" in text


def test_insert_module_after_rewires_downstream_edges() -> None:
    graph = VkdtGraph.parse(
        "\n".join(
            [
                "module:a:01",
                "module:b:01",
                "module:c:01",
                "connect:a:01:output:b:01:input",
                "connect:b:01:output:c:01:input",
            ]
        )
    )
    graph.insert_module_after("x", "01", after_module="b", after_instance="01")
    text = graph.to_text()
    assert "connect:b:01:output:x:01:input" in text
    assert "connect:x:01:output:c:01:input" in text
