from researchgit.ingestion.processing import chunk, _chat_text
def test_chunking_preserves_content(): assert "evidence" in " ".join(chunk("# Evidence\n\nEvidence matters."))
def test_chat_export_variants(): assert "hello" in _chat_text([{"text":"hello"}])
