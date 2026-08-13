import yaml
from typing import Union, Dict, Any, Optional, List, Tuple
from pathlib import Path
from src.schema import ScenarioConfig


class _AnchorTrackingComposer(yaml.composer.Composer):
    """Composer that records each node's anchor name.

    PyYAML keeps anchors in a per-composition dict that is discarded after
    parsing, so it is mirrored here as id(node) -> anchor name.
    """

    def __init__(self):
        super().__init__()
        self.node_anchors: Dict[int, str] = {}

    def _record(self, anchor: Optional[str], node: yaml.Node) -> yaml.Node:
        if anchor is not None:
            self.node_anchors[id(node)] = anchor
        return node

    def compose_scalar_node(self, anchor: Optional[str]) -> yaml.ScalarNode:
        return self._record(anchor, super().compose_scalar_node(anchor))

    def compose_sequence_node(self, anchor: Optional[str]) -> yaml.SequenceNode:
        return self._record(anchor, super().compose_sequence_node(anchor))

    def compose_mapping_node(self, anchor: Optional[str]) -> yaml.MappingNode:
        return self._record(anchor, super().compose_mapping_node(anchor))


class _AnchorTrackingLoader(yaml.reader.Reader, yaml.scanner.Scanner,
                            yaml.parser.Parser, _AnchorTrackingComposer,
                            yaml.constructor.BaseConstructor, yaml.resolver.BaseResolver):
    """Minimal loader that yields a compose tree plus anchor names."""

    def __init__(self, stream):
        yaml.reader.Reader.__init__(self, stream)
        yaml.scanner.Scanner.__init__(self)
        yaml.parser.Parser.__init__(self)
        _AnchorTrackingComposer.__init__(self)
        yaml.constructor.BaseConstructor.__init__(self)
        yaml.resolver.BaseResolver.__init__(self)


def _extract_variable_anchor_names(root: Optional[yaml.Node], node_anchors: Dict[int, str]) -> Optional[List[Optional[str]]]:
    """Return anchor names in declaration order for the .variables block.

    yaml.safe_load resolves aliases and discards anchor names, so a compose
    tree with recorded anchors is used. Returns None when no named list is
    present (e.g. .variables defined as a dict, or a dict source with no
    anchor info). Alias items resolve to their original anchored node and so
    report the original anchor name.
    """
    if root is None or not isinstance(root, yaml.nodes.MappingNode):
        return None
    for key_node, value_node in root.value:
        if key_node.value == ".variables":
            if isinstance(value_node, yaml.nodes.SequenceNode):
                return [node_anchors.get(id(item)) for item in value_node.value]
            return None
    return None


def _collect_node_paths(root: yaml.Node, node_anchors: Dict[int, str]) -> Dict[int, List[str]]:
    """Map each anchored node id to every dot-path where it appears in the tree.

    Because PyYAML resolves aliases to the *same* node object as the anchor
    declaration, the declaration and every alias reference share one id. Walking
    the compose tree collects all paths (declaration included) for each anchor,
    which lets callers derive which scenario fields a variable controls.

    Sequence items that are mappings with an ``id`` scalar (e.g. events,
    accounts) are keyed by that id so paths stay meaningful and stable even if
    list ordering changes; other sequence items use their positional index.
    """
    paths_by_id: Dict[int, List[str]] = {nid: [] for nid in node_anchors}

    def item_segment(item: yaml.Node, index: int) -> Optional[str]:
        if isinstance(item, yaml.nodes.MappingNode):
            for key_node, value_node in item.value:
                if key_node.value == "id" and isinstance(value_node, yaml.ScalarNode):
                    return str(value_node.value)
        return str(index)

    def walk(node: yaml.Node, path: List[str]) -> None:
        if isinstance(node, yaml.ScalarNode):
            if id(node) in paths_by_id:
                paths_by_id[id(node)].append(".".join(path))
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                walk(item, path + [item_segment(item, i)])
        elif isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                walk(value_node, path + [key_node.value])

    walk(root, [])
    return paths_by_id


def _extract_variable_alias_refs(root: yaml.Node, node_anchors: Dict[int, str]) -> Dict[str, List[str]]:
    """Map each variable name to the dot-paths where its anchor is referenced.

    Returns {var_name: [dot_paths]} excluding the `.variables` declaration
    itself. This is what lets the API update every field a life-decision toggle
    controls without hardcoding per-scenario event IDs.
    """
    paths_by_id = _collect_node_paths(root, node_anchors)
    refs: Dict[str, List[str]] = {}
    for node_id, name in node_anchors.items():
        paths = [p for p in paths_by_id.get(node_id, []) if not p.startswith(".variables")]
        if paths:
            refs[name] = paths
    return refs


def load_scenario_from_yaml(source: Union[str, Path, Dict[str, Any]], return_variables: bool = False) -> Union[ScenarioConfig, Tuple[ScenarioConfig, Dict[str, Any]]]:
    """
    Parses and validates a declarative scenario from a YAML file path, YAML raw string, or dictionary.
    If return_variables=True, returns tuple of (ScenarioConfig, variables_dict).
    Otherwise, returns just ScenarioConfig for backward compatibility.
    """
    root = None
    node_anchors: Dict[int, str] = {}
    if isinstance(source, dict):
        data = source
    elif isinstance(source, (str, Path)):
        # If source looks like a file path and exists, open it.
        # Otherwise, if it's a string, attempt to parse it as raw YAML content.
        is_path = False
        try:
            p = Path(source)
            if p.is_file():
                is_path = True
        except Exception:
            is_path = False

        if is_path:
            text = Path(source).read_text(encoding="utf-8")
        elif isinstance(source, str):
            text = source
        else:
            raise ValueError(f"Invalid path source: {source}")

        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"YAML content did not parse to a dict: {source}")
        loader = _AnchorTrackingLoader(text)
        try:
            root = loader.get_single_node()
        finally:
            loader.dispose()
        node_anchors = loader.node_anchors
    else:
        raise TypeError(f"Expected file path, raw YAML string, or dict, got {type(source)}")

    # Extract variables section (keys starting with .)
    variables = {k: v for k, v in data.items() if k.startswith(".")}

    # Recover anchor names (e.g. &social_security_enabled) so callers can address
    # variables by name instead of by positional index.
    if ".variables" in variables and isinstance(variables[".variables"], list):
        var_names = _extract_variable_anchor_names(root, node_anchors)
        if var_names:
            variables[".variable_names"] = var_names

    # Recover alias references so callers can update every field a variable
    # controls (e.g. step_adjustments referencing a life-decision toggle).
    if root is not None and isinstance(root, yaml.nodes.MappingNode):
        alias_refs = _extract_variable_alias_refs(root, node_anchors)
        if alias_refs:
            variables[".alias_refs"] = alias_refs

    # Strip dot-prefixed keys (e.g. .variables) — these are YAML-only authoring
    # helpers used to define anchors/aliases and must not be passed to Pydantic.
    scenario_data = {k: v for k, v in data.items() if not k.startswith(".")}

    config = ScenarioConfig.model_validate(scenario_data)

    if return_variables:
        return config, variables
    return config
