"""Check setup locally without making paid requests or printing secrets."""

import importlib.util

from server.config import settings
from server.memory import MMEMemory


def main():
    cfg = settings()
    issues = cfg.setup_issues()
    print(f"Pet: {cfg.name} ({cfg.pet_id})")
    print(f"Pipeline: {cfg.stt} → {cfg.llm} → {cfg.tts}")
    print(f"Memory: {cfg.memory}; local data: {cfg.data_dir}")
    print(
        f"Request limits: {cfg.max_turns_per_hour}/hour, {cfg.max_cloud_turns_per_day} cloud/day (UTC)"
    )
    if not cfg.uses_cloud:
        print(
            "DEMO: synthetic recognition, scripted replies and tones; no paid voice calls."
        )
    for selected, module, command in [
        (cfg.llm == "claude", "anthropic", "uv sync --extra cloud"),
        (cfg.memory == "mme", "mcp", "uv sync --extra memory"),
    ]:
        if selected and importlib.util.find_spec(module) is None:
            issues.append(f"Install {module}: {command}")
    if cfg.memory == "mme":
        try:
            MMEMemory(cfg.mme_config, cfg.mme_api_key.get_secret_value())
        except (OSError, ValueError, KeyError):
            issues.append(
                "Complete mme-config.json using your MME server's URL and tool schemas"
            )
    print(
        "Microphone client:",
        "installed"
        if importlib.util.find_spec("sounddevice")
        else "optional; install with uv sync --extra client",
    )
    print(
        "Billing: usage units are logged; set monetary limits in the provider dashboards."
    )
    for issue in issues:
        print("NEEDS YOU:", issue)
    print(
        "SETUP READY (live services still need testing)"
        if not issues
        else "SETUP INCOMPLETE"
    )
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
