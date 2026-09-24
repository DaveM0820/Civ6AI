"""Offline tests for autotest.env loading used by the in-game harness."""

import os
import tempfile


def apply_autotest_config(config_path, env, force=False):
	applied = env.get("_AUTOTEST_CONFIG_APPLIED") == "1"
	if applied and not force:
		return
	if not os.path.isfile(config_path):
		return
	for line in open(config_path, "r"):
		line = line.strip()
		if (not line) or line.startswith("#") or ("=" not in line):
			continue
		key, value = line.split("=", 1)
		env[key] = value
	env["_AUTOTEST_CONFIG_APPLIED"] = "1"


def is_autotest_mode(config_path, env):
	if os.path.isfile(config_path):
		if env.get("_AUTOTEST_CONFIG_APPLIED") != "1":
			apply_autotest_config(config_path, env)
		return True
	return env.get("CIV4AI_AUTOTEST") == "1"


def human_play_mode(config_path, env):
	return is_autotest_mode(config_path, env) and env.get("CIV4AI_HUMAN_PLAY") == "1"


def human_play_from_file(config_path):
	if not os.path.isfile(config_path):
		return False
	for line in open(config_path, "r"):
		line = line.strip()
		if line.startswith("CIV4AI_HUMAN_PLAY="):
			return line.split("=", 1)[1].strip() == "1"
	return False


def test_human_play_from_autotest_env_file():
	with tempfile.TemporaryDirectory() as tmp:
		path = os.path.join(tmp, "autotest.env")
		with open(path, "w") as handle:
			handle.write("CIV4AI_HUMAN_PLAY=1\nCIV4AI_SIDECAR_LIVE=1\n")
		env = {}
		assert human_play_mode(path, env) is True
		assert env.get("CIV4AI_SIDECAR_LIVE") == "1"
		assert human_play_from_file(path) is True


def test_process_env_autotest_without_file():
	with tempfile.TemporaryDirectory() as tmp:
		path = os.path.join(tmp, "missing.env")
		env = {"CIV4AI_AUTOTEST": "1", "CIV4AI_HUMAN_PLAY": "1"}
		assert is_autotest_mode(path, env) is True
		assert human_play_mode(path, env) is True


def test_human_play_file_fallback_without_process_env():
	with tempfile.TemporaryDirectory() as tmp:
		path = os.path.join(tmp, "autotest.env")
		with open(path, "w") as handle:
			handle.write("CIV4AI_HUMAN_PLAY=1\n")
		assert human_play_from_file(path) is True
