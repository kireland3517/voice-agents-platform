import sqlite3
import phonetics
import jellyfish

def normalize_surname(name):
    """Convert to uppercase, keep only A-Z"""
    return "".join(filter(str.isalpha, name)).upper()

def find_surname_candidates(asr_text, db_path='surnames.db'):
    """
    Find surname candidates based on phonetic matching.
    Returns list of (surname, similarity_score) tuples, sorted by score.
    """
    # Normalize input
    normalized_input = normalize_surname(asr_text)

    if not normalized_input:
        return []

    # Generate phonetic keys
    primary_key, secondary_key = phonetics.dmetaphone(normalized_input)

    # Query database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = '''
        SELECT DISTINCT surname_normalized
        FROM surnames
        WHERE metaphone_primary = ?
    '''
    params = [primary_key]

    # Add secondary key conditions if exists
    if secondary_key:
        query += '''
            OR metaphone_primary = ?
            OR metaphone_secondary = ?
            OR metaphone_secondary = ?
        '''
        params.extend([secondary_key, primary_key, secondary_key])

    cursor.execute(query, tuple(params))
    candidates = [row[0] for row in cursor.fetchall()]
    conn.close()

    # Rank by string similarity
    if candidates:
        scored = []
        for candidate in candidates:
            score = jellyfish.jaro_winkler_similarity(normalized_input, candidate)
            scored.append((candidate, score))

        # Sort by similarity score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    return []

def generate_llm_prompt(asr_text, candidates):
    """
    Generate appropriate LLM prompt based on candidate results.
    Returns dict with prompt type and text.
    """
    normalized_input = normalize_surname(asr_text)

    if not candidates:
        # Scenario 4: No match
        return {
            'type': 'no_match',
            'prompt': f"The customer's name '{asr_text}' was not found in the database. Ask the customer to please spell their last name for you."
        }

    # Get top candidate
    top_candidate, top_score = candidates[0]

    if len(candidates) == 1:
        if normalized_input == top_candidate:
            # Scenario 1: Perfect match
            spelling = '-'.join(top_candidate)
            return {
                'type': 'perfect_match',
                'prompt': f"The customer's last name is {top_candidate}. Confirm this by reading the spelling: {spelling}."
            }
        else:
            # Scenario 2: Single phonetic match
            spelling = '-'.join(top_candidate)
            return {
                'type': 'phonetic_match',
                'prompt': f"The customer said their name sounds like '{asr_text}'. The database suggests the correct spelling is '{top_candidate}'. Ask the customer to confirm this spelling: 'Is that spelled {spelling}?'"
            }

    # Scenario 3: Multiple matches
    if len(candidates) <= 3:
        options = []
        for candidate, _ in candidates:
            spelling = '-'.join(candidate)
            options.append(f"{candidate}, {spelling}")

        options_text = ', or '.join(options)
        return {
            'type': 'multiple_matches',
            'prompt': f"The customer's name sounds like '{asr_text}'. The database has several possible spellings. Ask for clarification by listing the options. For example: 'Thank you. I have a few options for that spelling. Is that {options_text}?'"
        }
    else:
        # Too many matches, just ask top 3
        options = []
        for candidate, _ in candidates[:3]:
            spelling = '-'.join(candidate)
            options.append(f"{candidate}, {spelling}")

        options_text = ', or '.join(options)
        return {
            'type': 'multiple_matches',
            'prompt': f"The customer's name sounds like '{asr_text}'. Ask for clarification with the most likely options: 'Is that {options_text}, or a different spelling?'"
        }

# Test function
def test_verifier(name):
    """Quick test function"""
    print(f"\nTesting: {name}")
    candidates = find_surname_candidates(name)
    print(f"Found {len(candidates)} candidates:")
    for surname, score in candidates[:5]:
        print(f"  {surname}: {score:.3f}")

    prompt = generate_llm_prompt(name, candidates)
    print(f"\nPrompt type: {prompt['type']}")
    print(f"Prompt: {prompt['prompt']}")

if __name__ == '__main__':
    # Run tests
    test_verifier('Smith')
    test_verifier('Frankowitz')
    test_verifier('Mier')
    test_verifier('Ngo')
