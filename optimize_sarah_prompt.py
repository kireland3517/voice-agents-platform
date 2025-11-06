#!/usr/bin/env python3
"""
Optimize Sarah Prompt Instructions
Adapted from OpenAI's prompt optimization system
Uses standard OpenAI API to detect and fix prompt issues
"""
import os
import sys
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any
from openai import AsyncOpenAI

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


async def check_contradictions(developer_message: str) -> Dict[str, Any]:
    """
    Check for logical contradictions in the prompt.
    """
    print("\n[1/5] Checking for contradictions...")

    system_prompt = """You are Dev-Contradiction-Checker.

Goal: Detect genuine self-contradictions or impossibilities inside the developer prompt.

Definitions:
• A contradiction = two clauses that cannot both be followed.
• Overlaps or redundancies are NOT contradictions.

Instructions:
1. Compare every imperative/prohibition against all others.
2. List at most FIVE contradictions (each as ONE bullet).
3. If no contradiction exists, say so.

Output format (strict JSON):
{
  "has_issues": <bool>,
  "issues": ["<bullet 1>", "<bullet 2>"]
}
"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Developer Message:\n\n{developer_message}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )

        result = json.loads(response.choices[0].message.content)

        if result.get("has_issues"):
            print(f"   Found {len(result.get('issues', []))} contradiction(s)")
        else:
            print("   No contradictions found")

        return result
    except Exception as e:
        print(f"   Error: {e}")
        return {"has_issues": False, "issues": []}


async def check_format(developer_message: str) -> Dict[str, Any]:
    """
    Check if format specifications are clear and complete.
    """
    print("\n[2/5] Checking format specifications...")

    system_prompt = """You are Format-Checker.

Task: Decide whether the developer prompt requires structured output (JSON/CSV/XML/Markdown table, etc.).
If so, flag any missing or unclear aspects of that format.

Steps:
1. Categorize as: "conversation_only" or "structured_output_required"
2. For structured output: Point out absent fields, ambiguous data types, unspecified ordering, or missing error-handling.

Be conservative - do NOT invent issues if unsure.

Output format (strict JSON):
{
  "has_issues": <bool>,
  "issues": ["<desc 1>", "..."]
}
Maximum five issues. No extra keys or text.
"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Developer Message:\n\n{developer_message}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )

        result = json.loads(response.choices[0].message.content)

        if result.get("has_issues"):
            print(f"   Found {len(result.get('issues', []))} format issue(s)")
        else:
            print("   Format specifications are clear")

        return result
    except Exception as e:
        print(f"   Error: {e}")
        return {"has_issues": False, "issues": []}


async def check_fewshot_consistency(
    developer_message: str,
    messages: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Check if few-shot examples are consistent with the developer prompt.
    """
    if not messages:
        return {"has_issues": False, "issues": [], "rewrite_suggestions": []}

    print(f"\n[3/5] Checking few-shot example consistency ({len(messages)} messages)...")

    system_prompt = """You are FewShot-Consistency-Checker.

Goal: Find conflicts between the DEVELOPER_MESSAGE rules and the accompanying assistant examples.

Method:
Extract key constraints from DEVELOPER_MESSAGE:
- Tone / style
- Forbidden or mandated content
- Output format requirements

Compliance Rubric - read carefully:
Evaluate only what the developer message makes explicit.

Objective constraints you must check when present:
- Required output type syntax (e.g., "JSON object", "single sentence", "subject line").
- Hard limits (length ≤ N chars, language required to be English, forbidden words, etc.).
- Mandatory tokens or fields the developer explicitly names.

Out-of-scope (DO NOT FLAG):
- Whether the reply "sounds generic", "repeats the prompt", or "fully reflects the user's request" - unless the developer text explicitly demands those qualities.
- Creative style, marketing quality, or depth of content unless stated.
- Minor stylistic choices (capitalisation, punctuation) that do not violate an explicit rule.

Pass/Fail rule:
- If an assistant reply satisfies all objective constraints, it is compliant, even if you personally find it bland or loosely related.
- Only record an issue when a concrete, quoted rule is broken.

For each assistant example:
- USER_EXAMPLES are for context only; never use them to judge compliance.
- Judge each assistant reply solely against the explicit constraints you extracted from the developer message.
- If a reply breaks a specific, quoted rule, add a line explaining which rule it breaks.
- Optionally, suggest a rewrite in one short sentence (add to rewrite_suggestions).
- If you are uncertain, do not flag an issue.
- Be conservative—uncertain or ambiguous cases are not issues.

Output format (strict JSON):
{
  "has_issues": <bool>,
  "issues": ["<explanation 1>", "..."],
  "rewrite_suggestions": ["<suggestion 1>", "..."]
}
List max five items for both arrays. Provide empty arrays when none. No markdown, no extra keys.
"""

    user_examples = [m["content"] for m in messages if m.get("role") == "user"]
    assistant_examples = [m["content"] for m in messages if m.get("role") == "assistant"]

    input_data = {
        "DEVELOPER_MESSAGE": developer_message,
        "USER_EXAMPLES": user_examples,
        "ASSISTANT_EXAMPLES": assistant_examples
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(input_data, indent=2)}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )

        result = json.loads(response.choices[0].message.content)

        if result.get("has_issues"):
            print(f"   Found {len(result.get('issues', []))} few-shot inconsistency(ies)")
        else:
            print("   Few-shot examples are consistent")

        return result
    except Exception as e:
        print(f"   Error: {e}")
        return {"has_issues": False, "issues": [], "rewrite_suggestions": []}


async def rewrite_prompt(
    original_message: str,
    contradiction_issues: Dict[str, Any],
    format_issues: Dict[str, Any]
) -> str:
    """
    Rewrite the prompt to fix identified issues.
    """
    print("\n[4/5] Rewriting prompt to fix issues...")

    system_prompt = """You are Dev-Rewriter.

You receive:
- ORIGINAL_DEVELOPER_MESSAGE
- CONTRADICTION_ISSUES (may be empty)
- FORMAT_ISSUES (may be empty)

Rewrite rules:
- Preserve the original intent and capabilities.
- Resolve each contradiction: Keep the clause that preserves intent; remove/merge conflicting ones.
- If FORMAT_ISSUES is non-empty: Append a new section titled "## Output Format" with clear schema/examples.
- Do NOT change few-shot examples.
- Do NOT add new policies or scope.

Output format (strict JSON):
{
  "new_developer_message": "<full rewritten text>"
}
"""

    input_data = {
        "ORIGINAL_DEVELOPER_MESSAGE": original_message,
        "CONTRADICTION_ISSUES": contradiction_issues,
        "FORMAT_ISSUES": format_issues
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(input_data, indent=2)}
            ],
            response_format={"type": "json_object"},
            temperature=0.5
        )

        result = json.loads(response.choices[0].message.content)
        print("   Prompt rewritten successfully")
        return result.get("new_developer_message", original_message)
    except Exception as e:
        print(f"   Error: {e}")
        return original_message


async def rewrite_fewshot(
    new_developer_message: str,
    original_messages: List[Dict[str, str]],
    fewshot_issues: Dict[str, Any]
) -> List[Dict[str, str]]:
    """
    Rewrite few-shot examples to align with the developer prompt.
    """
    if not original_messages or not fewshot_issues.get("has_issues"):
        return original_messages

    print(f"\n[5/5] Rewriting few-shot examples to fix inconsistencies...")

    system_prompt = """You are FewShot-Rewriter.

Input payload:
- NEW_DEVELOPER_MESSAGE (already optimized)
- ORIGINAL_MESSAGES (list of user/assistant dicts)
- FEW_SHOT_ISSUES (non-empty)

Task:
Regenerate only the assistant parts that were flagged.
User messages must remain identical.
Every regenerated assistant reply MUST comply with NEW_DEVELOPER_MESSAGE.

After regenerating each assistant reply, verify:
- It matches NEW_DEVELOPER_MESSAGE. ENSURE THAT THIS IS TRUE.

Output format (strict JSON):
{
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}

Guidelines:
- Preserve original ordering and total count.
- If a message was unproblematic, copy it unchanged.
"""

    input_data = {
        "NEW_DEVELOPER_MESSAGE": new_developer_message,
        "ORIGINAL_MESSAGES": original_messages,
        "FEW_SHOT_ISSUES": fewshot_issues
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(input_data, indent=2)}
            ],
            response_format={"type": "json_object"},
            temperature=0.5
        )

        result = json.loads(response.choices[0].message.content)
        messages = result.get("messages", original_messages)
        print(f"   Few-shot examples rewritten ({len(messages)} messages)")
        return messages
    except Exception as e:
        print(f"   Error: {e}")
        return original_messages


async def optimize_prompt(
    developer_message: str,
    messages: List[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Main optimization workflow - runs all 5 agents and rewrites if needed.
    """
    print("=" * 70)
    print("Starting Prompt Optimization (5-Agent System)")
    print("=" * 70)

    messages = messages or []

    # Run all checkers in parallel
    tasks = [
        check_contradictions(developer_message),
        check_format(developer_message),
    ]

    if messages:
        tasks.append(check_fewshot_consistency(developer_message, messages))

    results = await asyncio.gather(*tasks)

    # Unpack results
    contradiction_result = results[0]
    format_result = results[1]
    fewshot_result = results[2] if messages else {"has_issues": False, "issues": [], "rewrite_suggestions": []}

    # Rewrite prompt if needed
    prompt_needs_rewrite = (
        contradiction_result.get("has_issues", False) or
        format_result.get("has_issues", False)
    )

    final_prompt = developer_message
    if prompt_needs_rewrite:
        print(f"\nPrompt issues found - proceeding with rewrite")
        final_prompt = await rewrite_prompt(
            developer_message,
            contradiction_result,
            format_result
        )
    else:
        print(f"\nNo prompt issues found")

    # Rewrite few-shot examples if needed
    final_messages = messages
    if fewshot_result.get("has_issues"):
        print(f"\nFew-shot issues found - proceeding with rewrite")
        final_messages = await rewrite_fewshot(
            final_prompt,
            messages,
            fewshot_result
        )
    elif messages:
        print(f"\nNo few-shot issues found")

    any_changes = prompt_needs_rewrite or fewshot_result.get("has_issues", False)

    return {
        "changes_made": any_changes,
        "original_prompt": developer_message,
        "optimized_prompt": final_prompt,
        "original_messages": messages,
        "optimized_messages": final_messages,
        "contradiction_issues": contradiction_result.get("issues", []),
        "format_issues": format_result.get("issues", []),
        "fewshot_issues": fewshot_result.get("issues", []),
        "fewshot_suggestions": fewshot_result.get("rewrite_suggestions", [])
    }


async def main():
    """
    Load Sarah's instructions and optimize them.
    """
    # Check for API key
    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set")
        print("Please set it with: export OPENAI_API_KEY='your-key-here'")
        return

    # Load Sarah's instructions
    prompt_file = Path('sarah_instructions_senior_life.md')
    if not prompt_file.exists():
        print(f"Error: {prompt_file} not found")
        return

    print(f"Loading prompt from: {prompt_file}")
    prompt_text = prompt_file.read_text(encoding='utf-8')
    print(f"Original prompt: {len(prompt_text):,} characters, {len(prompt_text.split()):,} words\n")

    # Run optimization
    result = await optimize_prompt(prompt_text)

    # Display results
    print("\n" + "=" * 70)
    print("Optimization Results")
    print("=" * 70)

    if result["contradiction_issues"]:
        print("\n### Contradiction Issues:")
        for i, issue in enumerate(result["contradiction_issues"], 1):
            print(f"  {i}. {issue}")

    if result["format_issues"]:
        print("\n### Format Issues:")
        for i, issue in enumerate(result["format_issues"], 1):
            print(f"  {i}. {issue}")

    if result["fewshot_issues"]:
        print("\n### Few-Shot Consistency Issues:")
        for i, issue in enumerate(result["fewshot_issues"], 1):
            print(f"  {i}. {issue}")

    if result["fewshot_suggestions"]:
        print("\n### Few-Shot Rewrite Suggestions:")
        for i, suggestion in enumerate(result["fewshot_suggestions"], 1):
            print(f"  {i}. {suggestion}")

    if result["changes_made"]:
        print(f"\n### Changes Made: YES")
        print(f"Optimized prompt: {len(result['optimized_prompt']):,} characters")

        # Save optimized version
        output_file = Path('sarah_instructions_senior_life_optimized.md')
        output_file.write_text(result['optimized_prompt'], encoding='utf-8')
        print(f"\nOptimized prompt saved to: {output_file}")

        # Show diff stats
        original_words = len(result['original_prompt'].split())
        optimized_words = len(result['optimized_prompt'].split())
        word_diff = optimized_words - original_words
        print(f"\nWord count change: {original_words:,} → {optimized_words:,} ({word_diff:+,} words)")

        # Save optimized messages if any
        if result["optimized_messages"]:
            messages_file = Path('sarah_optimized_messages.json')
            with open(messages_file, 'w', encoding='utf-8') as f:
                json.dump(result["optimized_messages"], f, indent=2, ensure_ascii=False)
            print(f"Optimized messages saved to: {messages_file}")
    else:
        print(f"\n### Changes Made: NO")
        print("The prompt is already well-optimized!")

    # Export full results to JSON
    output_json = Path('sarah_prompt_optimization_results.json')
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nFull results exported to: {output_json}")

    print("\n" + "=" * 70)
    print("Optimization Complete!")
    print("=" * 70)


if __name__ == '__main__':
    asyncio.run(main())
