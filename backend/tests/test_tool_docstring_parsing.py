"""`parse_docstring`, which decides what a model is told about an argument.

Open WebUI generates a tool's JSON schema from its method docstring, so for
every tool on the instance -- the generated GeoTeaser shim, the built-ins, and
anything a user writes in the Workspace -- this function *is* the contract. It
matched `:param name: description` line by line and kept only the first line, so
a wrapped description lost everything after it, silently and completely.

The case that surfaced it: `:param run_mode:` is four lines of rules about when
a card may reuse a previous run's values, and the model was shown "clean or
carry_forward. clean is the default and is what". Cut mid-clause. The sentence
that says *only when the user explicitly asks* never reached it.

The tests here are the boundaries of the continuation rule, because a joiner
that is too eager is its own bug: it would pull `:return:` or the prose after a
blank line into the last parameter's description and tell the model something
the author did not write.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'backend'))

from open_webui.utils.tools import parse_docstring  # noqa: E402


def test_a_wrapped_description_arrives_whole():
    parsed = parse_docstring(
        """Do a thing.

        :param mode: clean or carry_forward. clean is the default
            and is what "start over" means.
        """
    )

    assert parsed['mode'] == (
        'clean or carry_forward. clean is the default and is what "start over" means.'
    )


def test_a_single_line_description_is_unchanged():
    """The overwhelmingly common shape, and the one a regression here would
    break for every tool at once."""
    parsed = parse_docstring(':param object_name: Geological object name.')

    assert parsed == {'object_name': 'Geological object name.'}


def test_the_next_parameter_ends_the_previous_one():
    parsed = parse_docstring(
        """
        :param first: one
            still one
        :param second: two
        """
    )

    assert parsed == {'first': 'one still one', 'second': 'two'}


def test_a_return_field_is_not_swallowed_into_the_last_parameter():
    parsed = parse_docstring(
        """
        :param only: one
            still one
        :return: Markdown result.
        """
    )

    assert parsed == {'only': 'one still one'}


def test_a_blank_line_ends_a_description():
    """Prose after the field list belongs to nobody. Joining across the blank
    line would put the author's closing paragraph in an argument's schema."""
    parsed = parse_docstring(
        """
        :param only: one

        Some closing prose that is not about the parameter.
        """
    )

    assert parsed == {'only': 'one'}


def test_a_runtime_injected_parameter_is_still_skipped_with_its_continuation():
    """`__user__` and friends are not model-visible, and neither are their
    continuation lines -- which would otherwise land on whichever parameter came
    before."""
    parsed = parse_docstring(
        """
        :param real: one
        :param __user__: injected
            and wrapped
        """
    )

    assert parsed == {'real': 'one'}


def test_no_docstring_is_no_parameters():
    assert parse_docstring(None) == {}
    assert parse_docstring('') == {}
