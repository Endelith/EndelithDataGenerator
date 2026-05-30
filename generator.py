import json
import argparse
import re
from pathlib import Path
from collections import defaultdict

# ─────────────────────────────────────────────
# Registry config
# ─────────────────────────────────────────────

REGISTRY: dict[str, dict] = {
    "banner_pattern": {},
    "cat_variant": {},
    "cat_sound_variant": {},
    "chat_type": {},
    "sound_event": {"source": "reports"},
    "chicken_variant": {},
    "chicken_sound_variant": {},
    "cow_variant": {},
    "cow_sound_variant": {},
    "clock_time_marker": {},
    "damage_type": {},
    "dimension_type": {},
    "enchantment": {},
    "frog_variant": {},
    "worldgen/biome": {},
    "timeline": {},
    "trim_material": {},
    "wolf_variant": {},
    "wolf_sound_variant": {},
    "item": {"source": "reports", "vanilla_value": True},
    "block": {"source": "custom_block"},
    "block_state": {"source": "custom_block_state"},
    "block_entity_type": {"source": "custom_block_entity_type"},
    "entity_type": {},
    "instrument": {},
    "jukebox_song": {},
    "painting_variant": {},
    "pig_variant": {},
    "pig_sound_variant": {},
    "world_clock": {}, 
    "zombie_nautilus_variant": {},
}

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description="Merge per-file Minecraft registry JSONs into arrays."
)

parser.add_argument(
    "--version",
    required=True,
    help="Minecraft version for known_pack (example: 26.1)"
)

parser.add_argument(
    "--input",
    default="data",
    help="Input directory (Minestom dump)"
)

parser.add_argument(
    "--output",
    default="merged",
    help="Output directory"
)

args = parser.parse_args()

# ─────────────────────────────────────────────
# SNBT Utility
# ─────────────────────────────────────────────

HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
SNBT_SIMPLE_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_\-.\+]+$")


def signed_int(value: int) -> int:
    if value > 0x7FFFFFFF:
        return value - 0x100000000

    return value


def to_snbt(obj):
    """Conversion of Python objects to SNBT strings with quoted values."""
    if isinstance(obj, bool):
        return "1b" if obj else "0b"

    if isinstance(obj, int):
        return str(obj)

    if isinstance(obj, str) and HEX_COLOR_PATTERN.match(obj):
        return str(signed_int(int(obj[1:], 16)))

    if isinstance(obj, float):
        value = f"{obj:.10f}".rstrip("0").rstrip(".")

        if "." not in value:
            value += ".0"

        return f"{value}f"

    if isinstance(obj, str):
        escaped = obj.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    if isinstance(obj, list):
        return "[" + ",".join(to_snbt(item) for item in obj) + "]"

    if isinstance(obj, dict):
        items = []

        for key, value in obj.items():
            key_str = str(key)

            if not SNBT_SIMPLE_KEY_PATTERN.match(key_str):
                escaped_key = key_str.replace("\\", "\\\\").replace('"', '\\"')
                key_str = f'"{escaped_key}"'

            items.append(f"{key_str}:{to_snbt(value)}")

        return "{" + ",".join(items) + "}"

    return str(obj)


# ─────────────────────────────────────────────
# Tag Inheritance Engine
# ─────────────────────────────────────────────

TAG_INDEX = defaultdict(lambda: defaultdict(set))


def index_tags(input_root: Path):
    tags_dir = input_root / "tags"

    if not tags_dir.exists():
        return

    all_tags = defaultdict(dict)

    for tag_file in tags_dir.rglob("*.json"):
        with open(tag_file, encoding="utf-8") as file:
            try:
                all_tags[tag_file.stem] = json.load(file)
            except json.JSONDecodeError:
                continue

    def resolve_tag(registry_stem, tag_id, visited=None):
        if visited is None:
            visited = set()

        if tag_id in visited:
            return set()

        visited.add(tag_id)

        tag_data = all_tags[registry_stem].get(tag_id, {})
        raw_values = tag_data.get("values", [])

        final_values = set()

        for value in raw_values:
            if isinstance(value, str) and value.startswith("#"):
                final_values.update(resolve_tag(registry_stem, value[1:], visited))
            else:
                final_values.add(value)

        return final_values

    for registry_stem, tags in all_tags.items():
        for tag_id in tags:
            values = resolve_tag(registry_stem, tag_id)

            for value in values:
                if isinstance(value, str):
                    TAG_INDEX[registry_stem][value].add(tag_id)


# ─────────────────────────────────────────────
# Merge Logic
# ─────────────────────────────────────────────

input_root = Path(args.input)
output_root = Path(args.output)


def process_registry(registry_type: str, cfg: dict):
    source = cfg.get("source")

    if registry_type in ["block", "block_state"]:
        input_file = input_root / "block.json"
    elif registry_type == "block_entity_type":
        input_file = input_root / "block_entity_types.json"
    else:
        input_file = input_root / f"{registry_type}.json"

    if not input_file.exists():
        print(f"[skip] {registry_type} (file not found: {input_file})")
        return

    with open(input_file, encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            print(f"[skip] {registry_type} (invalid JSON)")
            return

    entries = []
    registry_stem = Path(registry_type).stem

    for key, value in data.items():
        if source == "reports":
            if cfg.get("vanilla_value"):
                final_value = ["minecraft:vanilla"]
            else:
                final_value = {"sound": key}

            entry = {
                "key": key,
                "value": final_value
            }

        elif source == "custom_block":
            default_state = value.get("defaultStateId", 0)
            states_dict = value.get("states", {})
            state_ids = sorted(state["stateId"] for state in states_dict.values())

            entry = {
                "key": key,
                "value": {
                    "required_feature_flags": ["minecraft:vanilla"],
                    "default_state": default_state,
                    "states": state_ids
                }
            }

            tags = TAG_INDEX[registry_stem].get(key)

            if tags:
                entry["tags"] = sorted(list(tags))

        elif source == "custom_block_state":
            is_air = value.get("air", False)
            blocks_motion = value.get("blocksMotion", True)
            translation_key = value.get("translationKey", "").lower()
            is_leaves = "leaves" in key or "leaves" in translation_key

            states_dict = value.get("states", {})

            for state_repr, state_value in states_dict.items():
                properties = {}

                if state_repr.startswith("[") and state_repr.endswith("]"):
                    inner = state_repr[1:-1]

                    if inner:
                        for prop_pair in inner.split(","):
                            if "=" not in prop_pair:
                                continue

                            prop_key, prop_value = prop_pair.split("=", 1)
                            properties[prop_key] = prop_value

                block_state_value = {}

                if properties:
                    block_state_value["properties"] = properties

                if is_air:
                    block_state_value["air"] = True

                has_fluid = (
                    properties.get("waterlogged") == "true"
                    or key in ["minecraft:water", "minecraft:lava"]
                )

                if has_fluid:
                    block_state_value["has_fluid_state"] = True

                if not blocks_motion:
                    block_state_value["blocks_motion"] = False

                if is_leaves:
                    block_state_value["leaves"] = True

                entries.append({
                    "key": key,
                    "value": block_state_value
                })

            continue

        elif source == "custom_block_entity_type":
            entry = {
                "key": key,
                "value": [key]
            }

        else:
            entry = {
                "key": key,
                "value": to_snbt(value),
                "known_pack": {
                    "namespace": "minecraft",
                    "path": "core",
                    "version": args.version
                }
            }

            tags = TAG_INDEX[registry_stem].get(key)

            if tags:
                entry["tags"] = sorted(list(tags))

        entries.append(entry)

    parts = list(Path(registry_type).parts)
    filename = parts[-1]

    if not filename.endswith("s"):
        filename = filename + "s"

    output_file = output_root.joinpath(*parts[:-1], filename).with_suffix(".json")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(entries, file, indent=2, ensure_ascii=False)

    print(f"[merge] {registry_type} -> {output_file}")


index_tags(input_root)

for registry_type, cfg in REGISTRY.items():
    process_registry(registry_type, cfg)

print("\nDone! Merged files are in the 'merged' directory.")
