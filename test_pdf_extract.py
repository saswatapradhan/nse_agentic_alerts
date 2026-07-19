from ingestion import download_and_extract_text

test_url = "https://nsearchives.nseindia.com/corporate/5PAISA_17072026005010_EXINTIMATION.pdf"

print(f"Downloading and extracting text from:\n{test_url}\n")
text = download_and_extract_text(test_url)

if text:
    print(f"Successfully extracted {len(text)} characters")
    print("\n--- First 500 characters ---")
    print(text[:500])
else:
    print("Extraction failed — check error message above")