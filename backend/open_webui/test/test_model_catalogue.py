"""Pins the model catalogue (hardening plan Item 9).

Models are code now, and two properties of that code are easy to break silently:

1. **The prompt assembly.** The shared policy is stored once and combined with per-model slots.
   If someone reorders the slots or edits the wrong constant, every model's system prompt changes
   at once and nothing raises. These tests pin the exact assembled text for each model against
   the shape that was in production.

2. **The absent-means-permissive fields.** `meta.hidden`, `is_active` and the `builtinTools` map
   are all read so that a MISSING key is the enabling value. Dropping one does not error -- it
   un-hides an embedding model or re-enables a deferred tool. These tests fail if that happens.

No database, no app boot.
"""

import hashlib

from open_webui.model_catalogue import (
    AUTHORITATIVE_DATE,
    CODING_TAIL,
    IDENTITY,
    MODEL_CATALOGUE,
    POLICY,
    QWEN_REASONING_TAIL,
    system_prompt,
)

BY_ID = {entry['id']: entry for entry in MODEL_CATALOGUE}

# The five models that carry a system prompt, and which slots each one fills.
PROMPT_SHAPE = {
    'Qwen/Qwen3.6-35B-A3B': (AUTHORITATIVE_DATE, QWEN_REASONING_TAIL),
    'deepseek-ai/DeepSeek-V4-Flash-0731': ('', ''),
    'schat-quick': ('', ''),
    'schat-deepthink': ('', ''),
    'schat-coding': ('', CODING_TAIL),
}

# Infrastructure models are invoked by the platform, never chosen by a user, so they carry no
# prompt at all. A prompt appearing here would mean one was pasted onto the embedding or image
# model by mistake.
NO_PROMPT = {'google/gemma-4-E4B-it', 'Qwen/Qwen-Image', 'BAAI/bge-m3'}

# hidden=True keeps a model out of the selector. The three presets are the user-facing tiers and
# must stay selectable; everything else must stay hidden.
EXPECTED_HIDDEN = {
    'Qwen/Qwen3.6-35B-A3B': True,
    'google/gemma-4-E4B-it': True,
    'Qwen/Qwen-Image': True,
    'BAAI/bge-m3': True,
    'deepseek-ai/DeepSeek-V4-Flash-0731': True,
    'schat-quick': None,
    'schat-coding': None,
    'schat-deepthink': None,
}

PRESETS = ('schat-quick', 'schat-coding', 'schat-deepthink')
BASE_MODEL = 'deepseek-ai/DeepSeek-V4-Flash-0731'


# SHA-256 of each assembled prompt, taken from the models that were running in production and
# verified field-for-field against that export. This is the golden pin, and it is deliberately
# NOT expressed in terms of system_prompt() -- the test below that compares against the function
# is self-referential (both sides move together if the function changes), so it cannot catch a
# change to the assembly itself. These hashes can.
#
# A failure here is not necessarily a bug: editing the shared policy SHOULD break it. It means
# "the prompt text changed, confirm that was intended and update the hash in the same commit",
# which is exactly the review gate a governance artefact needs.
GOLDEN_PROMPT_SHA256 = {
    'Qwen/Qwen3.6-35B-A3B': ('406ffb3199318d34d89fa349e162c6d8aef127a4c461bdca1ece849fac145473', 2181),
    'deepseek-ai/DeepSeek-V4-Flash-0731': ('7b5434d8e965ea77ec76f126fb7a87ebb3980a5e0a0b53dddfaf9279854fcfec', 1903),
    'schat-quick': ('7b5434d8e965ea77ec76f126fb7a87ebb3980a5e0a0b53dddfaf9279854fcfec', 1903),
    'schat-coding': ('2ea95db20a8c945ddb2d218556cb42ab2b502eab5b5968ceb957d283836b2570', 2120),
    'schat-deepthink': ('7b5434d8e965ea77ec76f126fb7a87ebb3980a5e0a0b53dddfaf9279854fcfec', 1903),
}


def test_catalogue_ids_are_exactly_the_expected_set():
    assert set(BY_ID) == set(PROMPT_SHAPE) | NO_PROMPT


def test_assembled_prompts_match_the_golden_hashes():
    for model_id, (expected_sha, expected_len) in GOLDEN_PROMPT_SHA256.items():
        prompt = BY_ID[model_id]['system']
        assert len(prompt) == expected_len, model_id
        assert hashlib.sha256(prompt.encode()).hexdigest() == expected_sha, model_id


def test_flash_and_deepthink_share_the_base_prompt_exactly():
    """Three of the five prompts are the unmodified shared policy. If one drifts, the hash test
    above localises it; this one states the intent."""
    base = GOLDEN_PROMPT_SHA256['schat-quick'][0]
    for model_id in ('deepseek-ai/DeepSeek-V4-Flash-0731', 'schat-quick', 'schat-deepthink'):
        assert GOLDEN_PROMPT_SHA256[model_id][0] == base, model_id


def test_each_prompt_is_assembled_from_the_shared_policy():
    for model_id, (date, tail) in PROMPT_SHAPE.items():
        assert BY_ID[model_id]['system'] == system_prompt(date=date, tail=tail), model_id


def test_every_prompt_contains_the_shared_policy_verbatim():
    """The point of the shared constant: one edit moves every model together."""
    for model_id in PROMPT_SHAPE:
        assert POLICY in BY_ID[model_id]['system'], model_id
        assert BY_ID[model_id]['system'].startswith(IDENTITY), model_id


def test_the_date_block_precedes_the_policy():
    """Order is load-bearing -- the date is context the policy is read against, not a footnote."""
    prompt = BY_ID['Qwen/Qwen3.6-35B-A3B']['system']
    assert prompt.index(AUTHORITATIVE_DATE) < prompt.index(POLICY)


def test_only_qwen_carries_the_date_block():
    """Per-model on purpose: Qwen's thinking mode asserts a training-cutoff date, DeepSeek's
    has not shown that. If this starts failing, someone made a per-model fix global."""
    carriers = [m['id'] for m in MODEL_CATALOGUE if m['system'] and AUTHORITATIVE_DATE in m['system']]
    assert carriers == ['Qwen/Qwen3.6-35B-A3B']


def test_only_the_coder_tier_carries_the_coding_tail():
    carriers = [m['id'] for m in MODEL_CATALOGUE if m['system'] and CODING_TAIL in m['system']]
    assert carriers == ['schat-coding']


def test_infrastructure_models_have_no_system_prompt():
    for model_id in NO_PROMPT:
        assert BY_ID[model_id]['system'] is None, model_id


def test_hidden_flag_is_written_out_explicitly():
    """Absence un-hides: the frontend defaults `hidden` to False. So an infrastructure model
    losing this key becomes selectable as a chat model."""
    for model_id, expected in EXPECTED_HIDDEN.items():
        assert BY_ID[model_id]['meta'].get('hidden') is expected, model_id


def test_presets_chain_to_the_base_model():
    """The three tiers are overlays. Delete the base entry and they are orphaned."""
    for model_id in PRESETS:
        assert BY_ID[model_id]['base_model_id'] == BASE_MODEL, model_id
    assert BY_ID[BASE_MODEL]['base_model_id'] is None


def test_tiers_are_differentiated_by_parameters_not_by_prose():
    """Flash and Deepthink share a prompt on purpose -- depth belongs in the parameter. If these
    ever diverge in prose instead, the tier contract has moved to the wrong place."""
    assert BY_ID['schat-quick']['system'] == BY_ID['schat-deepthink']['system']
    quick = BY_ID['schat-quick']['params']['custom_params']['chat_template_kwargs']
    assert quick['thinking'] is False


def test_effort_ladder_is_the_decided_one():
    """Pinned, not merely range-checked.

    Coder shipped at 'low' -- the bottom rung on a model whose levels are low/high/max with no
    'medium' -- and nobody noticed, because a plausible-looking value in a data blob reads as
    intentional. Pinning makes a change to the ladder a reviewed decision, the same gate the
    golden prompt hashes provide. Update these alongside a measurement, not casually.
    """
    assert BY_ID['schat-coding']['params']['reasoning_effort'] == 'high'
    assert BY_ID['schat-deepthink']['params']['reasoning_effort'] == 'high'
    # 'max' is unmeasured on this model family; keep it out until someone measures it.
    efforts = [m['params'].get('reasoning_effort') for m in MODEL_CATALOGUE]
    assert 'max' not in efforts


def test_builtin_tools_are_written_out_rather_than_omitted():
    """utils/middleware.py reads `builtinTools.get(id, True)`, so a MISSING key ENABLES the tool.
    Every preset must therefore state each one explicitly."""
    for model_id in PRESETS:
        tools = BY_ID[model_id]['meta'].get('builtinTools')
        assert isinstance(tools, dict) and tools, model_id
        assert all(isinstance(v, bool) for v in tools.values()), model_id


def test_every_entry_has_the_fields_the_data_layer_requires():
    required = {'id', 'name', 'base_model_id', 'is_active', 'system', 'params', 'meta', 'created_at', 'updated_at'}
    for entry in MODEL_CATALOGUE:
        assert required <= set(entry), entry.get('id')
        assert entry['is_active'] is True, entry['id']
