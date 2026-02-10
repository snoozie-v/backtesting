#!/usr/bin/env python3
# generate_pine.py
"""
Generate TradingView Pine scripts from templates with optimized parameters.

Usage:
    python generate_pine.py v18                              # Generate from best_params
    python generate_pine.py v8_fast                          # Generate from best_params
    python generate_pine.py v18 --params-file custom.json    # Use custom params file
    python generate_pine.py --list                           # Show available templates
"""

import argparse
import json
import re
import sys
from pathlib import Path

RESULTS_DIR = Path("results")

# ============================================================================
# STRATEGY CONFIGURATIONS
# ============================================================================
# Each strategy maps Python param names -> Pine template placeholder names.
# Only params that differ in name need explicit mapping; same-name params
# are passed through automatically.

STRATEGY_CONFIGS = {
    "v18": {
        "template": "tradingview_v18.pine.template",
        "output": "tradingview_v18.pine",
        "param_map": {
            # Python param name -> Pine placeholder name
            # v18 names match 1:1, no remapping needed
        },
        "value_transforms": {
            # No transforms needed
        },
    },
    "v8_fast": {
        "template": "tradingview_v8_fast.pine.template",
        "output": "tradingview_v8_fast.pine",
        "param_map": {
            # Python param name -> Pine placeholder name (only where they differ)
            "max_single_up_bar": "max_single_up",
            "max_single_down_bar": "max_single_down",
            "volume_confirm": "use_volume",
            "daily_ema_period": "daily_ema_len",
            "use_partial_profits": "use_partial",
        },
        "value_transforms": {
            # No transforms needed
        },
    },
}


def format_pine_value(value):
    """Format a Python value for Pine Script syntax."""
    if isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, int):
        return str(value)
    elif isinstance(value, float):
        # Pine needs at least one decimal for floats
        formatted = f"{value:g}"
        if "." not in formatted:
            formatted += ".0"
        return formatted
    else:
        return str(value)


def load_best_params(strategy: str, params_file: str = None) -> dict:
    """Load best parameters from JSON file."""
    if params_file:
        filepath = Path(params_file)
    else:
        filepath = RESULTS_DIR / f"best_params_{strategy}.json"

    if not filepath.exists():
        print(f"Error: Params file not found: {filepath}")
        print(f"Run the optimizer first: python optimizer.py --strategy {strategy}")
        sys.exit(1)

    with open(filepath) as f:
        data = json.load(f)

    params = data.get("params", data)
    metrics = data.get("metrics", {})

    return params, metrics


def generate_pine(strategy: str, params_file: str = None):
    """Generate a Pine script from template with optimized params."""
    if strategy not in STRATEGY_CONFIGS:
        print(f"Error: No template configuration for strategy '{strategy}'")
        print(f"Available: {', '.join(STRATEGY_CONFIGS.keys())}")
        sys.exit(1)

    config = STRATEGY_CONFIGS[strategy]
    template_path = Path(config["template"])
    output_path = Path(config["output"])

    if not template_path.exists():
        print(f"Error: Template not found: {template_path}")
        sys.exit(1)

    # Load params
    params, metrics = load_best_params(strategy, params_file)

    # Build Pine placeholder -> value mapping
    param_map = config["param_map"]
    pine_values = {}

    for python_name, value in params.items():
        # Check if this param has a different Pine name
        pine_name = param_map.get(python_name, python_name)
        pine_values[pine_name] = format_pine_value(value)

    # Read template
    template_content = template_path.read_text()

    # Find all placeholders in template
    placeholders = set(re.findall(r"%%(\w+)%%", template_content))

    # Replace placeholders
    output_content = template_content
    replaced = []
    missing = []

    for placeholder in sorted(placeholders):
        token = f"%%{placeholder}%%"
        if placeholder in pine_values:
            output_content = output_content.replace(token, pine_values[placeholder])
            replaced.append((placeholder, pine_values[placeholder]))
        else:
            missing.append(placeholder)

    # Check for unreplaced placeholders
    if missing:
        print(f"Warning: {len(missing)} placeholder(s) not found in params:")
        for m in missing:
            print(f"  %%{m}%% - no matching param in best_params JSON")
        print()

    # Write output
    output_path.write_text(output_content)

    # Report
    print(f"Generated: {output_path}")
    print(f"Template:  {template_path}")
    if params_file:
        print(f"Params:    {params_file}")
    else:
        print(f"Params:    results/best_params_{strategy}.json")
    print()

    print(f"Parameters applied ({len(replaced)}):")
    for name, value in replaced:
        print(f"  {name} = {value}")

    if metrics:
        print()
        print("Optimization metrics:")
        for key, value in metrics.items():
            if value is not None:
                if isinstance(value, float):
                    print(f"  {key}: {value:.2f}")
                else:
                    print(f"  {key}: {value}")

    # Check for unused params (in JSON but no placeholder in template)
    unused = set(pine_values.keys()) - placeholders
    if unused:
        print()
        print(f"Note: {len(unused)} param(s) in JSON have no template placeholder:")
        for u in sorted(unused):
            print(f"  {u} = {pine_values[u]}")

    print()
    print(f"Done. Copy {output_path} contents into TradingView Pine Editor.")


def list_templates():
    """Show available templates and their status."""
    print("Available Pine templates:")
    print()

    for strategy, config in STRATEGY_CONFIGS.items():
        template_path = Path(config["template"])
        output_path = Path(config["output"])
        params_path = RESULTS_DIR / f"best_params_{strategy}.json"

        template_exists = template_path.exists()
        params_exists = params_path.exists()

        # Count placeholders in template
        placeholder_count = 0
        if template_exists:
            content = template_path.read_text()
            placeholders = set(re.findall(r"%%(\w+)%%", content))
            placeholder_count = len(placeholders)

        status = "READY" if (template_exists and params_exists) else "MISSING"
        if not template_exists:
            status += " (no template)"
        if not params_exists:
            status += " (no best_params)"

        print(f"  {strategy:<12} {placeholder_count} params   {status}")
        print(f"    Template: {template_path} {'[OK]' if template_exists else '[MISSING]'}")
        print(f"    Params:   {params_path} {'[OK]' if params_exists else '[MISSING]'}")
        print(f"    Output:   {output_path}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Generate TradingView Pine scripts from templates with optimized parameters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_pine.py v18                    Generate v18 Pine with optimized params
  python generate_pine.py v8_fast                Generate v8_fast Pine with optimized params
  python generate_pine.py v18 --params-file x.json  Use custom params file
  python generate_pine.py --list                 Show available templates
        """,
    )
    parser.add_argument("strategy", nargs="?", help="Strategy name (e.g., v18, v8_fast)")
    parser.add_argument("--params-file", "-p", help="Path to params JSON (default: results/best_params_{strategy}.json)")
    parser.add_argument("--list", "-l", action="store_true", help="List available templates")

    args = parser.parse_args()

    if args.list:
        list_templates()
        return 0

    if not args.strategy:
        parser.print_help()
        return 1

    generate_pine(args.strategy, args.params_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
