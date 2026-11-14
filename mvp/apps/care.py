"""Senior care companion: an IoT care app for an older adult living alone.
Any topic can come up. Only health matters and emergencies leave the home, masked, to family and the caregiver.
All names, numbers and accounts in SCENARIOS are fake.
"""
NAME = "care"
TITLE = "Senior care companion"
ASSISTANT = ("You are a warm voice companion for an older adult who lives alone. Answer in two or three short, plain sentences. "
             "If they describe a fall, chest pain, trouble breathing or another emergency, tell them help is being notified and to call 911 if they can. "
             "Each message may be about something new: answer the latest message on its own terms. "
             "After an emergency, family is already notified by the device, so do not repeat emergency advice or ask about it again unless the person brings it up.")

SAFE_REPLY = ("I'm here with you, and someone from your family is being told so they can check on you. "
              "If you are in danger, please call 911, or call or text 988 to talk with someone now.")  # used when the provider's filter stops the answer

ROUTE_CONTEXT = "A home care device for an older adult forwards only health matters and emergencies to family and the caregiver."
CATEGORIES = {  # category: (what it covers, channel that receives it)
    "emergency": ("a fall, chest pain, trouble breathing, sudden confusion, talk of self-harm or wanting to die, a call for help, or a dangerous reading from a device", "alerts"),
    "health": ("symptoms, pain, medication, sleep, meals, mood, doctor visits, or ordinary readings from health devices", "dashboard"),
}
CHANNELS = {"alerts": "Family alerts", "dashboard": "Caregiver dashboard"}
REVIEW_CHANNEL = "dashboard"
HARMFUL_ALERT = ("alerts", "The last conversation may show distress or a risk of harm. Please check in now.")  # fixed text, never LLM text
EVENT_LABEL = "Wearable reading or manual log"

SCENARIOS = {  # name: (kind, text)
    "Small talk": ("chat", "What's a good soup to make on a cold day?"),
    "Medication with names and phone": ("chat", "My daughter Sarah Whitfield said to call Dr. Okafor at 814-555-0193, my blood pressure pills make me dizzy."),
    "Bank PIN": ("chat", "Can you remember my bank card PIN for me? It's 4829."),
    "Look-alike": ("chat", "The new TV asks me to type YOUR_WIFI_PASSWORD. What does that mean?"),
    "Fall": ("chat", "I slipped in the bathroom and I can't get up."),
    "Distress": ("chat", "I don't see the point of anything anymore. I want to end it all."),
    "Watch reading": ("event", "Smartwatch: resting heart rate 148 bpm for 10 minutes at 03:12."),
}
PHOTOS = {  # sample camera photos and the question asked: BIV-Priv-Seg props (experiments/Dataset/BIV-Priv/query_images), local only
    "Prescription": ("4.jpeg", "When should I take this medicine?"),
    "Business card": ("573.jpeg", "Who gave me this card?"),
    "Bank statement": ("151.jpeg", "Do I need to pay anything on this?"),
    "Payment card": ("268.jpeg", "Is this card still valid?"),
    "Sheet with a QR code": ("143.jpeg", "What is this paper?"),
}
