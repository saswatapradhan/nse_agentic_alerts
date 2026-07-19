from agentic_analyzer import analyze_pdf_text, decide_alert

sample_text = """
NSE/BSE Corporate Announcement

Subject: Acquisition of majority stake in DataTech Solutions Pvt Ltd

The Board of Directors of Infosys Limited has approved the acquisition of 74% stake
in DataTech Solutions Pvt Ltd for a consideration of Rs. 850 Crore. This acquisition
will strengthen the company's AI and data analytics capabilities. The transaction is
expected to close within 60 days subject to regulatory approvals.
"""

print("Sending to GPT for analysis...")
signal = analyze_pdf_text(sample_text, symbol_hint="INFY", subject_hint="Acquisition of DataTech Solutions")

if signal:
    print("\n--- GPT's Analysis ---")
    for key, value in signal.items():
        print(f"{key}: {value}")

    print("\n--- Alert Decision ---")
    decision = decide_alert(signal)
    print(decision)
else:
    print("Analysis failed — check error message above")