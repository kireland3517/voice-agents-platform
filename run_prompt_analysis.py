#!/usr/bin/env python3
"""
Sarah Prompt Instructions Analysis Script
Analyzes the prompt file and outputs detailed metrics
"""
import re
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


def main():
    # Load prompt
    prompt_file = Path('sarah_instructions_senior_life.md')
    if not prompt_file.exists():
        print(f"[X] Error: {prompt_file} not found")
        return

    prompt_text = prompt_file.read_text(encoding='utf-8')
    print(f"[OK] Loaded prompt: {len(prompt_text):,} characters\n")

    # ========================================================================
    # 1. BASIC STATISTICS
    # ========================================================================
    lines = prompt_text.split('\n')
    words = prompt_text.split()
    sentences = [s.strip() for s in re.split(r'[.!?]+', prompt_text) if s.strip()]

    print("=" * 70)
    print(" " * 20 + "BASIC STATISTICS")
    print("=" * 70)
    print(f"Total Characters:        {len(prompt_text):,}")
    print(f"Total Lines:             {len(lines):,}")
    print(f"Non-Empty Lines:         {len([l for l in lines if l.strip()]):,}")
    print(f"Total Words:             {len(words):,}")
    print(f"Total Sentences:         {len(sentences):,}")
    print(f"Avg Words/Sentence:      {len(words) / max(1, len(sentences)):.1f}")

    # ========================================================================
    # 2. STRUCTURE ANALYSIS
    # ========================================================================
    headers = []
    header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

    for match in header_pattern.finditer(prompt_text):
        level = len(match.group(1))
        title = match.group(2).strip()
        headers.append({
            'level': level,
            'title': title,
            'position': match.start()
        })

    print(f"\n{'=' * 70}")
    print(" " * 20 + "DOCUMENT STRUCTURE")
    print("=" * 70)
    for h in headers:
        indent = "  " * (h['level'] - 1)
        print(f"{indent}{'#' * h['level']} {h['title']}")

    level_counts = Counter([h['level'] for h in headers])
    print(f"\nSection Count by Level:")
    for level in sorted(level_counts.keys()):
        print(f"  Level {level} ({'#' * level}): {level_counts[level]} sections")

    # ========================================================================
    # 3. CONTENT DISTRIBUTION
    # ========================================================================
    sections = []
    for i, h in enumerate(headers):
        if h['level'] == 2:  # Major sections only
            start = h['position']
            end = headers[i+1]['position'] if i+1 < len(headers) else len(prompt_text)
            content = prompt_text[start:end]
            sections.append({
                'title': h['title'],
                'words': len(content.split()),
                'characters': len(content)
            })

    sections_sorted = sorted(sections, key=lambda x: x['words'], reverse=True)

    print(f"\n{'=' * 70}")
    print(" " * 15 + "CONTENT DISTRIBUTION BY SECTION")
    print("=" * 70)
    print(f"{'Section':<40} {'Words':>10} {'Chars':>12}")
    print("-" * 70)
    for s in sections_sorted:
        print(f"{s['title']:<40} {s['words']:>10,} {s['characters']:>12,}")

    # ========================================================================
    # 4. TONE ANALYSIS
    # ========================================================================
    tone_keywords = {
        'Warmth': ['warm', 'caring', 'kind', 'friendly', 'welcoming', 'genuine'],
        'Professionalism': ['professional', 'polite', 'formal', 'courteous', 'respectful'],
        'Empathy': ['empathetic', 'understanding', 'supportive', 'patient', 'compassionate'],
        'Confidence': ['confident', 'assured', 'reliable', 'clear', 'knowledgeable'],
        'Caution': ['careful', 'cautious', 'never', 'avoid', 'do not']
    }

    tone_scores = {}
    text_lower = prompt_text.lower()

    for category, keywords in tone_keywords.items():
        count = sum(text_lower.count(kw) for kw in keywords)
        tone_scores[category] = count

    print(f"\n{'=' * 70}")
    print(" " * 25 + "TONE ANALYSIS")
    print("=" * 70)
    for category, count in sorted(tone_scores.items(), key=lambda x: x[1], reverse=True):
        bar = '#' * count
        print(f"{category:20s}: {bar} {count}")

    # ========================================================================
    # 5. TOOLS ANALYSIS
    # ========================================================================
    tool_pattern = r'###\s+([a-z_]+)\(([^)]+)\)([^#]+)'
    tools = []

    for match in re.finditer(tool_pattern, prompt_text):
        tool_name = match.group(1)
        parameters = match.group(2)
        description = match.group(3)

        is_proactive = 'PROACTIVE' in match.group(0)

        tools.append({
            'name': tool_name,
            'parameters': parameters.strip(),
            'is_proactive': is_proactive
        })

    print(f"\n{'=' * 70}")
    print(" " * 25 + "TOOL ANALYSIS")
    print("=" * 70)
    print(f"Total Tools Defined: {len(tools)}\n")

    for tool in tools:
        print(f"> {tool['name']}")
        print(f"   Parameters: {tool['parameters']}")
        print(f"   Proactive: {'[OK] Yes' if tool['is_proactive'] else '[X] No'}")
        print()

    # ========================================================================
    # 6. CONVERSATION FLOW
    # ========================================================================
    flow_section = re.search(r'## Conversation Flow(.+?)(?=##|$)', prompt_text, re.DOTALL)
    steps = []

    if flow_section:
        flow_text = flow_section.group(1)
        step_matches = re.findall(r'###\s+(\d+[a-z]?)\)\s+(.+?)(?=###|$)', flow_text, re.DOTALL)

        for step_num, step_content in step_matches:
            title_match = re.search(r'^(.+?)\n', step_content)
            title = title_match.group(1).strip() if title_match else 'Unnamed'

            exit_match = re.search(r'\*\*Exit when\*\*:(.+?)(?=\n\n|$)', step_content, re.DOTALL)
            exit_condition = exit_match.group(1).strip() if exit_match else 'Not specified'

            steps.append({
                'number': step_num,
                'title': title,
                'exit': exit_condition
            })

    print(f"{'=' * 70}")
    print(" " * 20 + "CONVERSATION FLOW PATHS")
    print("=" * 70)
    print(f"Total Flow Steps: {len(steps)}\n")

    for step in steps:
        print(f"Step {step['number']}: {step['title']}")
        print(f"   Exit: {step['exit'][:60]}{'...' if len(step['exit']) > 60 else ''}")
        print()

    # ========================================================================
    # 7. REQUIRED vs OPTIONAL FIELDS
    # ========================================================================
    info_collection = re.search(r'### 2b\) New Policy — Information Collection(.+?)(?=###|$)', prompt_text, re.DOTALL)

    required_fields = []
    optional_fields = []

    if info_collection:
        content = info_collection.group(1)

        required_match = re.search(r'\*\*Required\*\*:(.+?)(?=\*\*|\n\n)', content, re.DOTALL)
        if required_match:
            required_fields = [f.strip() for f in required_match.group(1).split(',')]

        optional_match = re.search(r'\*\*Optional\*\*:(.+?)(?=\*\*|\n\n)', content, re.DOTALL)
        if optional_match:
            optional_fields = [f.strip() for f in optional_match.group(1).split(',')]

    print(f"{'=' * 70}")
    print(" " * 20 + "FIELD REQUIREMENTS")
    print("=" * 70)
    print(f"Required Fields: {', '.join(required_fields) if required_fields else 'Not extracted'}")
    print(f"Optional Fields: {', '.join(optional_fields) if optional_fields else 'Not extracted'}")

    # ========================================================================
    # 8. PROHIBITIONS & CRITICAL RULES
    # ========================================================================
    prohibitions = []

    never_pattern = r'([Nn]ever[^.!?]+[.!?])'
    for match in re.finditer(never_pattern, prompt_text):
        prohibitions.append(match.group(1).strip())

    donot_pattern = r'([Dd]o not[^.!?]+[.!?])'
    for match in re.finditer(donot_pattern, prompt_text):
        prohibitions.append(match.group(1).strip())

    critical_rules = []
    critical_pattern = r'(\*\*CRITICAL[^\*]+\*\*|[Aa]lways[^.!?]+[.!?])'
    for match in re.finditer(critical_pattern, prompt_text):
        critical_rules.append(match.group(1).strip())

    print(f"\n{'=' * 70}")
    print(" " * 20 + "PROHIBITED BEHAVIORS")
    print("=" * 70)
    print(f"Total Prohibitions: {len(prohibitions)}\n")
    for i, prohibition in enumerate(prohibitions[:10], 1):
        print(f"{i}. {prohibition[:70]}{'...' if len(prohibition) > 70 else ''}")

    print(f"\n{'=' * 70}")
    print(" " * 22 + "CRITICAL RULES")
    print("=" * 70)
    print(f"Total Critical Rules: {len(critical_rules)}\n")
    for i, rule in enumerate(critical_rules[:10], 1):
        clean_rule = re.sub(r'\*\*', '', rule)
        print(f"{i}. {clean_rule[:70]}{'...' if len(clean_rule) > 70 else ''}")

    # ========================================================================
    # 9. EXAMPLE PHRASES
    # ========================================================================
    quote_pattern = r'"([^"]+)"'
    examples = []

    for match in re.finditer(quote_pattern, prompt_text):
        example = match.group(1)
        if len(example) > 15 and not example.startswith('$'):
            examples.append(example)

    categories = {
        'Greetings': [],
        'Confirmations': [],
        'Questions': [],
        'Closings': [],
        'Other': []
    }

    for example in examples:
        if any(word in example.lower() for word in ['thank', 'hello', 'hi', 'calling']):
            categories['Greetings'].append(example)
        elif any(word in example.lower() for word in ['correct', 'confirm', 'right', 'have that']):
            categories['Confirmations'].append(example)
        elif '?' in example:
            categories['Questions'].append(example)
        elif any(word in example.lower() for word in ['goodbye', 'have a', 'take care']):
            categories['Closings'].append(example)
        else:
            categories['Other'].append(example)

    print(f"\n{'=' * 70}")
    print(" " * 18 + "EXAMPLE PHRASES & TEMPLATES")
    print("=" * 70)
    print(f"Total Example Phrases: {len(examples)}\n")

    for category, phrases in categories.items():
        if phrases:
            print(f"\n{category} ({len(phrases)}):")
            for phrase in phrases[:5]:
                print(f"  • {phrase[:65]}{'...' if len(phrase) > 65 else ''}")

    # ========================================================================
    # 10. COMPLETENESS ASSESSMENT
    # ========================================================================
    completeness_checks = {
        'Has Role Definition': bool(re.search(r'## Role', prompt_text)),
        'Has Personality Guidelines': bool(re.search(r'## Personality', prompt_text)),
        'Has Tools Documentation': bool(re.search(r'## Tools', prompt_text)),
        'Has Conversation Flow': bool(re.search(r'## Conversation Flow', prompt_text)),
        'Has Examples': len(examples) > 10,
        'Has Safety Guidelines': bool(re.search(r'## Safety', prompt_text)),
        'Has Error Handling': bool(re.search(r'(repair|error|fail)', prompt_text, re.IGNORECASE)),
        'Has Escalation Path': bool(re.search(r'escalat', prompt_text, re.IGNORECASE)),
        'Has Edge Cases': 'ambiguous' in prompt_text.lower() or 'unclear' in prompt_text.lower(),
        'Has Required Phrases': bool(re.search(r'(exact|required|always say)', prompt_text, re.IGNORECASE))
    }

    passed = sum(completeness_checks.values())
    total = len(completeness_checks)
    score = (passed / total) * 100

    print(f"\n{'=' * 70}")
    print(" " * 20 + "COMPLETENESS ASSESSMENT")
    print("=" * 70)

    for check, result in completeness_checks.items():
        status = '[OK]' if result else '[X]'
        print(f"{status} {check}")

    print(f"\n[STATS] Completeness Score: {score:.1f}% ({passed}/{total})")

    # ========================================================================
    # 11. QUALITY METRICS
    # ========================================================================
    quality_metrics = {
        'Specificity (examples per 1k words)': len(examples) / max(1, len(words)) * 1000,
        'Structure Depth (max header level)': max([h['level'] for h in headers]) if headers else 0,
        'Rule Density (rules per 1k words)': len(prohibitions + critical_rules) / max(1, len(words)) * 1000,
        'Tool Coverage': len(tools)
    }

    print(f"\n{'=' * 70}")
    print(" " * 23 + "QUALITY METRICS")
    print("=" * 70)
    for metric, value in quality_metrics.items():
        print(f"{metric:40s}: {value:.2f}")

    # ========================================================================
    # 12. SUMMARY REPORT
    # ========================================================================
    if score >= 90:
        quality_grade = "Excellent (A)"
    elif score >= 80:
        quality_grade = "Very Good (B)"
    elif score >= 70:
        quality_grade = "Good (C)"
    else:
        quality_grade = "Needs Improvement (D)"

    print(f"\n{'=' * 70}")
    print(" " * 18 + "SARAH PROMPT ANALYSIS SUMMARY")
    print("=" * 70)

    print(f"\n[DOC] DOCUMENT OVERVIEW")
    print(f"   Total Words: {len(words):,}")
    print(f"   Total Sections: {len(headers)}")
    print(f"   Completeness Score: {score:.1f}%")

    print(f"\n[TARGET] KEY COMPONENTS")
    print(f"   Conversation Flow Steps: {len(steps)}")
    print(f"   Tools Defined: {len(tools)}")
    print(f"   Example Phrases: {len(examples)}")

    proactive_tools = [t for t in tools if t['is_proactive']]
    print(f"\n[TOOL] TOOL CONFIGURATION")
    print(f"   Proactive Tools: {len(proactive_tools)}")
    print(f"   Reactive Tools: {len(tools) - len(proactive_tools)}")

    print(f"\n[RULES] RULES & CONSTRAINTS")
    print(f"   Prohibitions (Never/Do Not): {len(prohibitions)}")
    print(f"   Critical Rules (Always/Critical): {len(critical_rules)}")

    print(f"\n[TONE] TOP TONE CHARACTERISTICS")
    top_tones = sorted(tone_scores.items(), key=lambda x: x[1], reverse=True)[:3]
    for category, count in top_tones:
        print(f"   {category}: {count} indicators")

    print(f"\n[STATS] OVERALL QUALITY: {quality_grade}")

    print(f"\n{'=' * 70}")
    print("Analysis complete!")
    print("=" * 70)

    # ========================================================================
    # 13. EXPORT TO JSON
    # ========================================================================
    analysis_results = {
        'statistics': {
            'total_characters': len(prompt_text),
            'total_words': len(words),
            'total_sentences': len(sentences),
            'avg_words_per_sentence': len(words) / max(1, len(sentences))
        },
        'sections': sections,
        'tools': tools,
        'tone_scores': tone_scores,
        'completeness_score': score,
        'quality_metrics': quality_metrics,
        'prohibitions_count': len(prohibitions),
        'critical_rules_count': len(critical_rules),
        'example_phrases_count': len(examples),
        'conversation_steps': len(steps)
    }

    output_file = 'sarah_prompt_analysis_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(analysis_results, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Detailed analysis results exported to: {output_file}")


if __name__ == '__main__':
    main()
