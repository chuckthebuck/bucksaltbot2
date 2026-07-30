import pytest

from chuck_salt_shack.expressions import evaluate_expression, parse_expression
from chuck_salt_shack.spec import WorkflowSpec, recipe_with_invocation


def recipe(**updates):
    data = {
        "version": 1,
        "name": "Example bot",
        "wiki": {"code": "commons", "family": "commons"},
        "source": {
            "type": "titles",
            "titles": ["User:Example/Sandbox"],
            "limit": 10,
            "namespaces": [2],
        },
        "filters": {"skip_redirects": True, "skip_missing": True},
        "transforms": [
            {
                "type": "literal_replace",
                "find": "old",
                "replace": "new",
            }
        ],
        "save": {"summary": "Saltlick on {{pagename}}"},
        "limits": {"max_edits": 10},
    }
    data.update(updates)
    return data


def test_workflow_normalizes_a_valid_recipe():
    workflow = WorkflowSpec.from_dict(recipe())

    assert workflow.name == "Example bot"
    assert workflow.source.titles == ("User:Example/Sandbox",)
    assert workflow.source.limit == 1
    assert workflow.transforms[0].type == "literal_replace"
    assert workflow.as_dict()["wiki"]["code"] == "commons"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source", {"type": "titles", "titles": []}, "at least one"),
        (
            "source",
            {"type": "category", "target": "", "limit": 10},
            "requires a target",
        ),
        ("transforms", [], "at least one"),
    ],
)
def test_workflow_rejects_incomplete_recipes(field, value, message):
    data = recipe()
    data[field] = value

    with pytest.raises(ValueError, match=message):
        WorkflowSpec.from_dict(data)


def test_expression_supports_conditional_regex_transform():
    expression = (
        'regex(r"old", "new", text, flags="i") '
        'if contains(lower(text), "old") else text'
    )

    assert (
        evaluate_expression(
            expression,
            text="OLD value",
            title="Sandbox",
            namespace=0,
        )
        == "new value"
    )


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "text.__class__",
        "[value for value in text]",
        "(lambda: text)()",
    ],
)
def test_expression_rejects_python_escape_hatches(expression):
    with pytest.raises(ValueError):
        parse_expression(expression)


def test_expression_rejects_unbounded_multiplication():
    with pytest.raises(ValueError, match="too large"):
        evaluate_expression(
            '"x" * 999999999',
            text="",
            title="Sandbox",
            namespace=0,
        )


def test_generated_bot_invocation_accepts_only_documented_inputs_and_arguments():
    merged = recipe_with_invocation(
        recipe(),
        inputs={"titles": ["User:Example/Other"]},
        arguments={"max_edits": 1, "summary": "One edit"},
    )

    assert merged["source"]["titles"] == ["User:Example/Other"]
    assert merged["limits"]["max_edits"] == 1
    assert merged["save"]["summary"] == "One edit"

    with pytest.raises(ValueError, match="unsupported invocation"):
        recipe_with_invocation(recipe(), arguments={"handler": "evil:run"})
