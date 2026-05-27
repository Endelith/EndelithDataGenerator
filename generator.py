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

def to_snbt(obj):
    """Conversion of Python objects to SNBT strings with quoted values."""
    if isinstance(obj, bool):
        return "1b" if obj else "0b"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, str) and re.match(r'^#[0-9A-Fa-f]{6}$', obj):
        return str(int(obj[1:], 16))
    if isinstance(obj, float):
        # Format with at least one decimal and 'f' suffix
        s = f"{obj:.10f}".rstrip('0').rstrip('.')
        if '.' not in s: s += ".0"
        return f"{s}f"
    if isinstance(obj, str):
        escaped = obj.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(obj, list):
        return "[" + ",".join(to_snbt(i) for i in obj) + "]"
    if isinstance(obj, dict):
        items = []
        for k, v in obj.items():
            key_str = str(k)
            if not re.match(r'^[a-zA-Z0-9_\-\.\+]+$', key_str):
                key_str = f'"{key_str.replace("\\", "\\\\").replace("\"", "\\\"")}"'
            items.append(f"{key_str}:{to_snbt(v)}")
        return "{" + ",".join(items) + "}"
    return str(obj)

# ─────────────────────────────────────────────
# Tag Inheritance Engine
# ─────────────────────────────────────────────

TAG_INDEX = defaultdict(lambda: defaultdict(set))

def index_tags(input_root: Path):
    tags_dir = input_root / "tags"
    if not tags_dir.exists(): return

    all_tags = defaultdict(dict)
    for tag_file in tags_dir.rglob("*.json"):
        with open(tag_file, encoding="utf-8") as f:
            try:
                all_tags[tag_file.stem] = json.load(f)
            except: continue

    def resolve_tag(registry_stem, tag_id, visited=None):
        if visited is None: visited = set()
        if tag_id in visited: return set()
        visited.add(tag_id)

        tag_data = all_tags[registry_stem].get(tag_id, {})
        raw_values = tag_data.get("values", [])
        
        final_values = set()
        for val in raw_values:
            if isinstance(val, str) and val.startswith("#"):
                final_values.update(resolve_tag(registry_stem, val[1:], visited))
            else:
                final_values.add(val)
        return final_values

    for registry_stem, tags in all_tags.items():
        for tag_id in tags:
            values = resolve_tag(registry_stem, tag_id)
            for val in values:
                if isinstance(val, str):
                    TAG_INDEX[registry_stem][val].add(tag_id)

# ─────────────────────────────────────────────
# Merge Logic
# ─────────────────────────────────────────────

input_root = Path(args.input)
output_root = Path(args.output)

def process_registry(registry_type: str, cfg: dict):
    source = cfg.get("source")
    
    # Determine input file path
    if registry_type in ["block", "block_state"]:
        input_file = input_root / "block.json"
    elif registry_type == "block_entity_type":
        input_file = input_root / "block_entity_types.json"
    else:
        input_file = input_root / f"{registry_type}.json"

    if not input_file.exists():
        print(f"[skip] {registry_type} (file not found: {input_file})")
        return

    with open(input_file, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except:
            print(f"[skip] {registry_type} (invalid JSON)")
            return

    entries = []
    registry_stem = Path(registry_type).stem

    for key, val in data.items():
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
            # Extract default state and all state IDs
            default_state = val.get("defaultStateId", 0)
            states_dict = val.get("states", {})
            state_ids = sorted([s["stateId"] for s in states_dict.values()])
            
            entry = {
                "key": key,
                "value": {
                    "required_feature_flags": ["minecraft:vanilla"],
                    "default_state": default_state,
                    "states": state_ids
                }
            }
            # Add tags
            tags = TAG_INDEX[registry_stem].get(key)
            if tags:
                entry["tags"] = sorted(list(tags))
        elif source == "custom_block_state":
            is_air = val.get("air", False)
            blocks_motion = val.get("blocksMotion", True)
            is_leaves = "leaves" in key or "leaves" in val.get("translationKey", "").lower()
            
            states_dict = val.get("states", {})
            for state_repr, state_val in states_dict.items():
                properties = {}
                if state_repr.startswith("[") and state_repr.endswith("]"):
                    inner = state_repr[1:-1]
                    if inner:
                        for prop_pair in inner.split(","):
                            if "=" in prop_pair:
                                p_k, p_v = prop_pair.split("=", 1)
                                properties[p_k] = p_v
                
                v = {}
                if properties:
                    v["properties"] = properties
                
                if is_air:
                    v["air"] = True
                
                has_fluid = properties.get("waterlogged") == "true" or key in ["minecraft:water", "minecraft:lava"]
                if has_fluid:
                    v["has_fluid_state"] = True
                
                if not blocks_motion:
                    v["blocks_motion"] = False
                
                if is_leaves:
                    v["leaves"] = True
                
                entries.append({
                    "key": key,
                    "value": v
                })
            continue # Already appended for this block
        elif source == "custom_block_entity_type":
            entry = {
                "key": key,
                "value": [key]
            }
        else:
            # Dynamic Registry
            entry = {
                "key": key,
                "value": to_snbt(val),
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

    # Prepare output path
    parts = list(Path(registry_type).parts)
    filename = parts[-1]
    if not filename.endswith("s"):
        filename = filename + "s"
    
    output_file = output_root.joinpath(*parts[:-1], filename).with_suffix(".json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    
    print(f"[merge] {registry_type} -> {output_file}")

# 1. Index tags
index_tags(input_root)

# 2. Process all configured registries
for registry_type, cfg in REGISTRY.items():
    process_registry(registry_type, cfg)

print("\nDone! Merged files are in the 'merged' directory.")
