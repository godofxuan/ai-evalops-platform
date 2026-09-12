"""Pinned BFCL Python single-turn pilot, not a full BFCL leaderboard runner.

Only SHA-256 verified upstream source is compiled. Model output is parsed as AST,
never executed; the upstream parser's eval-capable nodes are rejected first.
"""

from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import json
import re
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SOURCE_SHA = "f7cf7359b7ac615a0b294831c5ba2bc95ee4a000"
SOURCE_REPOSITORY = "https://github.com/ShishirPatil/gorilla"
PREFIX = "berkeley-function-call-leaderboard/bfcl_eval/"
CATEGORIES = ("simple_python", "multiple", "parallel", "irrelevance")
SOURCE_HASHES = {
    "LICENSE": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    PREFIX + "eval_checker/ast_eval/ast_checker.py": (
        "2aae7a68461a8f76c0be3894c8901b66b56967a1989d3ab066051e3fb97f1538"
    ),
    PREFIX + "eval_checker/eval_runner.py": (
        "b1033684908819ccb312d4d0e2c563359d69247412f00206013b2292b0e3ce81"
    ),
    PREFIX
    + "model_handler/utils.py": "f78fd3edce603b333dc9a88ee2c041dc547d51f71aa449ffebc044c4b1e353f3",
    PREFIX
    + "constants/enums.py": "2182becfa2a1d071ee1db30db593b4758c6bf866aa12d2d4b8daf09175ea518a",
    PREFIX + "constants/default_prompts.py": (
        "4cc033be99ae2b10bbde30e7751ddcac5468cb45841b6dc7b3a97b92adf38205"
    ),
    PREFIX + "utils.py": "3703b9bb63f83581c60b8e0b82aac74c360c9ca781e99e7d4eb28b0cce2285dd",
    PREFIX + "data/BFCL_v4_simple_python.json": (
        "82dd63ba502eb2520c6b5d1d9a5c4b590e03ff261565175561f6228a367d1991"
    ),
    PREFIX + "data/possible_answer/BFCL_v4_simple_python.json": (
        "90cd5bc653690ee8e459b5b3f3fc9458606f7f3fcbf795bb51b7dc581f8c86dc"
    ),
    PREFIX + "data/BFCL_v4_multiple.json": (
        "aef168155ebd74b7ac2401198b201343bc7d16d7a3d7e0d4e6d8ee82c6969b2a"
    ),
    PREFIX + "data/possible_answer/BFCL_v4_multiple.json": (
        "244e00ce9395df948bcafc7bee64e8f9c87ef70887587d83cae45b13699f3047"
    ),
    PREFIX + "data/BFCL_v4_parallel.json": (
        "19f51a82eff42e5d62541aa500115a056eb78f437c2ba1f10415fd7c8e5dda84"
    ),
    PREFIX + "data/possible_answer/BFCL_v4_parallel.json": (
        "8a6aa19c1adddc6a5a2f7e40f9dbf30cc7e95815e7b830c90589ab318229e0f0"
    ),
    PREFIX + "data/BFCL_v4_irrelevance.json": (
        "2b6ed4c2e992cdcf5f1678a701851f944bef7550ee026ed1ddb89efed5be01a6"
    ),
}


class BFCLSourceError(ValueError):
    """Pinned public source is missing or has changed."""


class BFCLSafetyError(ValueError):
    """An output cannot safely enter the unmodified upstream AST parser."""


def _verified_bytes(source_dir: Path, relative: str) -> bytes:
    expected = SOURCE_HASHES[relative]
    try:
        raw = (source_dir / relative).read_bytes()
    except OSError as exc:
        raise BFCLSourceError(f"missing_source:{relative}") from exc
    if hashlib.sha256(raw).hexdigest() != expected:
        raise BFCLSourceError(f"source_hash_mismatch:{relative}")
    return raw


def validate_sources(source_dir: Path) -> dict[str, str]:
    """Fail closed before executing any upstream code or using any gold labels."""
    for relative in SOURCE_HASHES:
        _verified_bytes(source_dir, relative)
    return dict(SOURCE_HASHES)


def _load_selected(
    source_dir: Path,
    relative: str,
    namespace: dict[str, Any],
    *,
    functions: set[str] | None = None,
    assignments: bool = False,
    classes: bool = False,
) -> None:
    """Load exact upstream AST nodes; imports and unrelated functions are excluded."""
    tree = ast.parse(_verified_bytes(source_dir, relative).decode("utf-8"))
    selected: list[ast.stmt] = []
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and (functions is None or node.name in functions):
            selected.append(node)
            found.add(node.name)
        elif (assignments and isinstance(node, (ast.Assign, ast.AnnAssign))) or (
            classes and isinstance(node, ast.ClassDef)
        ):
            selected.append(node)
    if functions is not None and found != functions:
        raise BFCLSourceError(f"missing_upstream_function:{functions - found}")
    module = ast.Module(body=selected, type_ignores=[])
    # This is verified upstream source, NOT model-generated output.
    exec(compile(module, f"bfcl@{SOURCE_SHA}/{relative}", "exec"), namespace)


def _forbidden_execution(*args: object, **kwargs: object) -> None:
    raise BFCLSafetyError("upstream_dynamic_execution_disabled")


def guard_model_output(raw_output: str) -> None:
    """Reject upstream eval branches, oversized inputs and excessive AST complexity."""
    if len(raw_output) > 65_536:
        raise BFCLSafetyError("output_too_large")
    cleaned = raw_output.strip("`\n ")
    if not cleaned.startswith("["):
        cleaned = "[" + cleaned
    if not cleaned.endswith("]"):
        cleaned += "]"
    cleaned = cleaned.strip().strip("'")
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError:
        # The official decoder decides how ordinary syntax errors are scored.
        return
    nodes = list(ast.walk(tree))
    if len(nodes) > 4096:
        raise BFCLSafetyError("ast_too_complex")
    if any(isinstance(node, (ast.BinOp, ast.Lambda)) for node in nodes):
        raise BFCLSafetyError("upstream_eval_capable_node")


def load_official_checker(source_dir: Path) -> dict[str, Any]:
    """Return a verified, Python-only closure of original BFCL grading functions.

    The model config only controls dotted-name rewriting. Prompt-mode outputs
    preserve dotted function names, so underscore_to_dot is explicitly False.
    No upstream model SDK, server, execution harness or non-Python parser runs.
    """
    validate_sources(source_dir)
    safe_builtins = dict(vars(builtins))
    for name in ("eval", "exec", "compile", "open", "input", "__import__"):
        safe_builtins[name] = _forbidden_execution
    namespace: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "__name__": "evalops_verified_bfcl",
        "ast": ast,
        "re": re,
        "json": json,
        "Enum": Enum,
        "BaseHandler": object,
        "MODEL_CONFIG_MAPPING": {"evalops-prompt": SimpleNamespace(underscore_to_dot=False)},
    }
    _load_selected(
        source_dir, PREFIX + "constants/enums.py", namespace, functions=set(), classes=True
    )
    _load_selected(
        source_dir,
        PREFIX + "constants/default_prompts.py",
        namespace,
        functions=set(),
        assignments=True,
    )
    _load_selected(
        source_dir,
        PREFIX + "utils.py",
        namespace,
        functions={
            "is_function_calling_format_output",
            "is_empty_output",
            "is_java",
            "is_js",
            "_get_language_specific_hint",
            "_func_doc_language_specific_pre_processing",
            "extract_prompt_format_from_id",
        },
    )
    _load_selected(
        source_dir,
        PREFIX + "model_handler/utils.py",
        namespace,
        functions={
            "ast_parse",
            "resolve_ast_call",
            "resolve_ast_by_type",
            "default_decode_ast_prompting",
            "parse_prompt_variation_params",
            "formulate_system_prompt",
            "format_function_doc",
            "system_prompt_pre_processing_chat_model",
        },
    )
    _load_selected(
        source_dir, PREFIX + "eval_checker/ast_eval/ast_checker.py", namespace, assignments=True
    )
    _load_selected(
        source_dir,
        PREFIX + "eval_checker/eval_runner.py",
        namespace,
        functions={"_evaluate_single_relevance_entry"},
    )
    return namespace


def build_messages(case: dict[str, Any], checker: dict[str, Any]) -> list[dict[str, str]]:
    """Construct official default prompting messages; never include ground truth."""
    if case["category"] not in CATEGORIES or len(case["question"]) != 1:
        raise ValueError("unsupported_case_scope")
    functions = checker["_func_doc_language_specific_pre_processing"](
        copy.deepcopy(case["function"]), case["category"]
    )
    messages: list[dict[str, str]] = checker["system_prompt_pre_processing_chat_model"](
        copy.deepcopy(case["question"][0]), functions, case["id"]
    )
    return messages


def grade_case(
    case: dict[str, Any],
    raw_output: str,
    source_dir: Path,
    *,
    checker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Grade an observed response; adapter failures remain in the fixed denominator."""
    if case.get("category") not in CATEGORIES:
        raise ValueError("unsupported_case_scope")
    engine = checker if checker is not None else load_official_checker(source_dir)
    result: dict[str, Any] = {
        "case_id": case["id"],
        "category": case["category"],
        "scorer": "pinned_bfcl_python_ast_subset",
        "source_sha": SOURCE_SHA,
        "valid": False,
        "official_valid": None,
        "parse_failed": False,
        "adapter_safety_rejected": False,
        "decoded_output": None,
    }
    if not raw_output.strip():
        return {**result, "error_type": "adapter_empty_response"}
    try:
        guard_model_output(raw_output)
    except (BFCLSafetyError, RecursionError, MemoryError) as exc:
        return {
            **result,
            "error_type": f"adapter_safety_rejected:{exc}",
            "adapter_safety_rejected": True,
        }
    decoded = None
    decode_error = None
    try:
        decoded = engine["default_decode_ast_prompting"](
            raw_output, engine["ReturnFormat"].PYTHON, False
        )
    except Exception as exc:
        decode_error = f"{type(exc).__name__}:{exc}"
    result.update(
        decoded_output=decoded, parse_failed=decode_error is not None, decode_error=decode_error
    )
    if case["category"] == "irrelevance":
        handler = SimpleNamespace(decode_ast=engine["default_decode_ast_prompting"])
        official = engine["_evaluate_single_relevance_entry"](
            handler, case["id"], raw_output, case, "evalops-prompt", "irrelevance"
        )
    elif decode_error is not None:
        return {**result, "official_valid": False, "error_type": "decode_error"}
    else:
        try:
            official = engine["ast_checker"](
                copy.deepcopy(case["function"]),
                decoded,
                copy.deepcopy(case["ground_truth"]),
                engine["Language"].PYTHON,
                case["category"],
                "evalops-prompt",
            )
        except Exception as exc:
            return {
                **result,
                "error_type": "official_checker_exception",
                "error": f"{type(exc).__name__}:{exc}",
            }
    return {
        **result,
        "official_valid": bool(official["valid"]),
        "valid": bool(official["valid"]),
        "official_result": official,
        "error_type": official.get("error_type"),
    }


def prepare_pilot(root: Path, per_category: int = 25) -> dict[str, Any]:
    """Freeze N rows per category by source/category/ID hash, before responses."""
    if not 1 <= per_category <= 25:
        raise ValueError("per_category_must_be_1_to_25")
    source_dir = root / "upstream"
    checker = load_official_checker(source_dir)
    cases: list[dict[str, Any]] = []
    available: dict[str, int] = {}
    for category in CATEGORIES:
        question_path = PREFIX + f"data/BFCL_v4_{category}.json"
        questions = [
            json.loads(line)
            for line in _verified_bytes(source_dir, question_path).decode("utf-8").splitlines()
            if line.strip()
        ]
        available[category] = len(questions)
        answers = None
        if category != "irrelevance":
            answer_path = PREFIX + f"data/possible_answer/BFCL_v4_{category}.json"
            answers = [
                json.loads(line)
                for line in _verified_bytes(source_dir, answer_path).decode("utf-8").splitlines()
                if line.strip()
            ]
            if len(answers) != len(questions):
                raise BFCLSourceError(f"question_answer_count_mismatch:{category}")
        ranked_indices = sorted(
            range(len(questions)),
            key=lambda index: hashlib.sha256(
                f"{SOURCE_SHA}/{category}/{questions[index]['id']}".encode()
            ).hexdigest(),
        )
        for index in ranked_indices[:per_category]:
            question = questions[index]
            if answers is not None and answers[index]["id"] != question["id"]:
                raise BFCLSourceError(f"question_answer_id_mismatch:{category}:{index}")
            case = {
                **question,
                "category": category,
                "source_index": index,
                "source_sha": SOURCE_SHA,
                "source_question_path": question_path,
                "ground_truth": answers[index]["ground_truth"] if answers else None,
            }
            case["messages"] = build_messages(case, checker)
            cases.append(case)
    if len({case["id"] for case in cases}) != len(cases):
        raise BFCLSourceError("duplicate_case_id")
    cases_bytes = (json.dumps(cases, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest = {
        "schema": "evalops-bfcl-public-pilot/1",
        "source_repository": SOURCE_REPOSITORY,
        "source_sha": SOURCE_SHA,
        "license": "Apache-2.0",
        "selection_rule": "lowest_sha256_of_source_sha_slash_category_slash_id_per_category",
        "per_category": per_category,
        "case_count": len(cases),
        "available_per_category": available,
        "case_ids": [case["id"] for case in cases],
        "cases_sha256": hashlib.sha256(cases_bytes).hexdigest(),
        "upstream_sha256": SOURCE_HASHES,
        "scorer_scope": "unmodified_pinned_official_python_ast_function_subset",
        "model_name_conversion": "prompt_mode_preserve_dotted_function_names",
        "prompt_format": checker["DEFAULT_SYSTEM_PROMPT_FORMAT"],
        "safety": "reject_BinOp_Lambda_before_official_parser_and_disable_dynamic_execution",
        "not_claimed": [
            "full_BFCL_leaderboard",
            "native_function_calling",
            "tool_execution",
            "multi_turn",
            "held_out_contamination_free",
        ],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    root.mkdir(parents=True, exist_ok=True)
    for name, raw in (("cases.json", cases_bytes), ("manifest.json", manifest_bytes)):
        destination = root / name
        if destination.exists():
            if destination.read_bytes() != raw:
                raise BFCLSourceError(f"refuse_to_overwrite_frozen_pilot:{name}")
        else:
            with destination.open("xb") as stream:
                stream.write(raw)
    return manifest
