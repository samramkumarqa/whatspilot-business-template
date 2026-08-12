import os
from dotenv import load_dotenv

# Load .env once
load_dotenv()

# ----------------------------------------
# App
# ----------------------------------------

DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ----------------------------------------
# This deployment's business
# ----------------------------------------
# Every customer gets their own deployment of this repo, all pointed at
# the same shared Postgres (see database/db.py) - the registry in the
# admin app's database has every customer's row in it. BUSINESS_ID is
# what confines *this* deployment to serving only its own customer: set
# it to the business_id assigned when this business was registered in
# the admin app's Businesses page (see api/auth.py's login check). Set
# automatically by the admin app's provisioning step for repos it
# creates; set manually here for local dev against an existing business.

BUSINESS_ID = os.getenv("BUSINESS_ID")

# ----------------------------------------
# Twilio
# ----------------------------------------

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# ----------------------------------------
# Business-owner login (WhatsApp/SMS OTP via Twilio Verify)
# ----------------------------------------
# /business-login shows a clear in-page error rather than crashing the
# app if TWILIO_VERIFY_SERVICE_SID isn't set yet (see verify.py). Create
# a Verify Service at https://console.twilio.com/us1/develop/verify/services
# and paste its SID into .env once ready.
#
# OTP_CHANNEL defaults to "sms" because Twilio Verify's WhatsApp channel
# requires a registered *production* WhatsApp sender (not available on
# the Sandbox) plus Meta-approved Authentication Templates - see
# verify.py's module docstring. Switch this to "whatsapp" once that
# sender is approved; nothing else in the code needs to change.
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID")
OTP_CHANNEL = os.getenv("OTP_CHANNEL", "sms")

# ----------------------------------------
# Session
# ----------------------------------------

SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")

# ----------------------------------------
# AI Providers
# ----------------------------------------
# NOTE: only Groq is actually used anywhere in this codebase.

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ----------------------------------------
# Vector Database
# ----------------------------------------
# Overridable via CHROMA_DB_PATH so production can point this at a
# persistent disk mount instead of the repo-relative default used locally.

CHROMA_DB = os.getenv("CHROMA_DB_PATH", "./chroma_db")

# ----------------------------------------
# Logging
# ----------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
