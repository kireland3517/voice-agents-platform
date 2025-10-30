from surname_verifier import find_surname_candidates, generate_llm_prompt

def verify_surname_for_voice_agent(asr_transcribed_name, db_path='surnames.db'):
    """
    Main integration point for voice agent.

    Args:
        asr_transcribed_name: Raw text from ASR (e.g., "frankowitz")
        db_path: Path to surnames database

    Returns:
        dict with:
            - candidates: list of (surname, score) tuples
            - prompt_type: 'perfect_match', 'phonetic_match', 'multiple_matches', 'no_match'
            - llm_prompt: text to send to LLM for natural response
            - top_match: most likely surname (or None)
            - confidence_score: score for top match
    """
    candidates = find_surname_candidates(asr_transcribed_name, db_path)
    prompt_data = generate_llm_prompt(asr_transcribed_name, candidates)

    return {
        'candidates': candidates,
        'prompt_type': prompt_data['type'],
        'llm_prompt': prompt_data['prompt'],
        'top_match': candidates[0][0] if candidates else None,
        'confidence_score': candidates[0][1] if candidates else 0.0
    }

# Example usage in your voice agent
if __name__ == '__main__':
    # Simulate ASR output
    test_names = ['Smith', 'Frankowitz', 'Johnson', 'rare_xyz_name']

    for asr_output in test_names:
        print(f"\n{'='*60}")
        print(f"ASR Output: {asr_output}")
        print(f"{'='*60}")

        result = verify_surname_for_voice_agent(asr_output)

        print(f"\nTop Match: {result['top_match']}")
        print(f"Confidence: {result['confidence_score']:.2%}")
        print(f"Prompt Type: {result['prompt_type']}")
        print(f"\nSend to LLM:\n{result['llm_prompt']}")
