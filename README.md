# ⚡ Zero-Cost ($0.00) Dual-Route Virtual Fax Gateway (Anywhere ➔ USA)

A production-grade, 100% free virtual fax transmission engine designed for sending PDF documents from anywhere in the world to United States government agencies (IRS, USCIS, County Election Boards, State Departments) with **$0.00 out-of-pocket cost**, no Twilio subscriptions, and zero per-page fees.

---

## 🚀 Quick Start: How to Send a Fax 

If you haven't sent a fax in months and just need the quick steps, follow this 3-step workflow:

### 1. Drop your PDF(s) into `outbox/`
Put the PDF file(s) you want to transmit into your project's `outbox/` folder:
```bash
~/TechProject/VirtualFax/outbox/
```
*(You can drag-and-drop files directly in macOS Finder).*

### 2. Run `./send.sh` from Terminal
Open Terminal and navigate to the project directory:
```bash
cd ~/TechProject/VirtualFax
```

Choose one of these commands:

- **Auto-Detect Newest File (Fastest):**  
  If you dropped your document into `outbox/`, you don't even need to type the filename:
  ```bash
  ./send.sh 510-272-6982 "Alameda County Registrar"
  ```

- **Specify a Specific File:**
  ```bash
  ./send.sh 510-272-6982 "Alameda County Registrar" ApplicationForm.pdf
  ```

- **Send Multiple Files (Auto-Merged):**  
  List multiple files—they will be merged into a single consolidated fax:
  ```bash
  ./send.sh 510-272-6982 "County Clerk" Form.pdf ID.pdf SupportingDoc.pdf
  ```

- **Send to US Toll-Free Government Line (IRS, USCIS, Social Security):**
  ```bash
  ./send.sh 800-829-1040 "IRS ITIN Operations" FormW7.pdf
  ```

### 3. Check Delivery Proof in `receipts/`
When the transmission completes, delivery receipts with confirmation codes and tracking URLs are saved automatically:
```bash
ls -l receipts/
```

> **Automated Zero-Cost Protection:**  
> The script boots your US EC2 micro-gateway, transmits through a native US IP to prevent geoblocks, and automatically powers down the EC2 server immediately upon completion—guaranteeing 0 wasted Free-Tier hours ($0.00 cost).

---

## 🏛️ Architecture Overview

The gateway operates an **intelligent Dual-Route Engine** that classifies destination numbers using the North American Numbering Plan (NANP) and automatically selects the optimal zero-cost path:

```
                            ┌────────────────────────┐
                            │    PDF Document In     │
                            │  (IRS / USCIS / Gov)   │
                            └───────────┬────────────┘
                                        │
                                        ▼
                            ┌────────────────────────┐
                            │  NANP Router & Parser  │
                            │     (gateway/router)   │
                            └───────────┬────────────┘
                                        │
                  ┌─────────────────────┴─────────────────────┐
                  │                                           │
         Toll-Free Destination                       Geographic Destination
      (800, 888, 877, 866, 855, 844, 833)            (e.g., 202, 510, 415, 312)
                  │                                           │
                  ▼                                           ▼
      ┌───────────────────────┐                   ┌───────────────────────┐
      │  ROUTE A: VoIP Engine │                   │ ROUTE B: Web Gateway  │
      │  (Ghostscript TIFF-F) │                   │  (Playwright Relay)   │
      └───────────┬───────────┘                   └───────────┬───────────┘
                  │                                           │
                  ▼                                           ▼
      ┌───────────────────────┐                   ┌───────────────────────┐
      │ Asterisk 20 + SpanDSP │                   │  FaxZero Web Portal   │
      │  (T.30 / T.38 UDPTL)  │                   │ (Free 3-Page Tier $0) │
      └───────────┬───────────┘                   └───────────┬───────────┘
                  │                                           │
                  ▼                                           ▼
      ┌───────────────────────┐                   ┌───────────────────────┐
      │  Open 8YY SIP Trunk   │                   │  Gmail IMAP Listener  │
      │(Alcazar/sip-trunk.info│                   │ (Auto-Approve Confirm)│
      │    Reverse-Billed)    │                   └───────────┬───────────┘
      └───────────┬───────────┘                               │
                  │                                           ▼
                  │                               ┌───────────────────────┐
                  │                               │  HTTP Auto-Activation │
                  │                               │ (Queued Transmission) │
                  │                               └───────────┬───────────┘
                  │                                           │
                  └─────────────────────┬─────────────────────┘
                                        │
                                        ▼
                            ┌────────────────────────┐
                            │   US Government Agency │
                            │     Physical Fax Machine│
                            └────────────────────────┘
```

---

## 💡 Telephony Economics: How Toll-Free Faxing is 100% Free ($0.00)

In the United States (NANPA), **8YY numbers** (`800`, `888`, `877`, `866`, `855`, `844`, `833`) are legally **reverse-billed**. The receiving organization (e.g., the IRS) pays the terminating carrier for incoming calls and faxes. 

Because carriers receive compensation or database dip fees for completing inbound 8YY traffic, several wholesale VoIP networks provide **unauthenticated open SIP toll-free termination**:
- `tf.alcazarnetworks.com:5060` (Alcazar Networks 8YY Gateway)
- `tollfree.sip-trunk.info:5060` (Fallback open gateway)

By pairing an open SIP trunk with **Ghostscript** (converting PDFs into ITU-T T.4/T.30 Group 4 TIFFs) and **Asterisk SpanDSP** (`res_fax_spandsp`), we can transmit multi-page faxes to any US toll-free government fax line with **no account balance, no API keys, and $0.00 cost**.

For local geographic numbers (e.g., county registrars in `510` Oakland or state departments in `202` Washington D.C.), Route B leverages automated browser relay (Playwright) via high-reputation free web portals coupled with an asynchronous **Gmail IMAP auto-activation listener** that polls and validates confirmation emails within seconds.

---

## 📁 Repository Structure

```
.
├── .env.example                  # Template configuration (Gmail App Password, SIP Trunks)
├── Dockerfile.asterisk           # Containerized Asterisk 20+ with SpanDSP & PJSIP
├── docker-compose.yml            # Docker deployment for the VoIP engine
├── faxctl                        # Executable CLI launcher
├── requirements.txt              # Python 3.12+ dependencies
├── pytest.ini                    # Test suite configuration
├── config/
│   ├── gateway_config.yaml       # Agency directories & routing policies
│   └── asterisk/
│       ├── asterisk.conf         # PBX directories and operational settings
│       ├── extensions.conf       # SendFAX dialplan context with T.30 telemetry
│       ├── manager.conf          # Asterisk Manager Interface (AMI) credentials
│       ├── modules.conf          # Module loader (res_fax, res_fax_spandsp, pjsip)
│       ├── pjsip.conf            # Open 8YY SIP trunks & transports
│       └── rtp.conf              # Media RTP & T.38 port allocation
├── gateway/
│   ├── cli.py                    # Main Click & Rich CLI entrypoint
│   ├── config.py                 # Pydantic Settings & YAML loader
│   ├── converter.py              # Ghostscript PDF -> ITU-T TIFF Class F engine
│   ├── router.py                 # NANP parser & toll-free vs geographic classifier
│   ├── routes/
│   │   ├── base.py               # Abstract route interface & FaxResult model
│   │   ├── voip_route.py         # Route A: Asterisk AMI / Call file / 8YY SIP
│   │   └── web_route.py          # Route B: Web Gateway + IMAP Orchestrator
│   ├── web/
│   │   ├── base_gateway.py       # Web gateway interface
│   │   ├── faxzero.py            # Playwright automation adapter for FaxZero
│   │   └── imap_listener.py      # Async Gmail IMAP confirmation listener
│   └── utils/
│       ├── logger.py             # Rich formatting & logging
│       ├── retry.py              # Exponential backoff with jitter
│       └── system_check.py       # Doctor diagnostics & US IP geolocation check
└── tests/
    ├── test_cli.py               # CLI command & dry-run tests
    ├── test_converter.py         # PDF inspection & TIFF magic byte checks
    ├── test_imap_listener.py     # Regex URL extraction & MIME parser tests
    └── test_router.py            # NANP validation & toll-free routing tests
```

---

## 🚀 Quickstart & Setup

### 1. Prerequisites

- **Python 3.12+**
- **Ghostscript (`gs`)**: Converts PDFs to ITU-T Fax TIFF Class F.
  - macOS: `brew install ghostscript`
  - Ubuntu / Debian: `sudo apt-get update && sudo apt-get install -y ghostscript`
- **Docker** (Optional, required for live Route A Asterisk VoIP transmission):
  - macOS: Docker Desktop
  - Ubuntu: `sudo apt-get install -y docker.io docker-compose-v2`

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/swikarpat/VirtualFax.git
cd VirtualFax

# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and Playwright Chromium
pip install -r requirements.txt
playwright install chromium
```

### 3. Configuration (`.env`)

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` to supply your email and sender info:

```env
FAX_SENDER_NAME="Taxpayer Legal Services"
FAX_SENDER_COMPANY="Independent Petitioner"
FAX_SENDER_EMAIL="your-email@gmail.com"
FAX_SENDER_PHONE="2025550199"
FAX_STATION_ID="+18005550199"

# Gmail IMAP Credentials (Required for Route B Auto-Activation)
# Generate a 16-character App Password at:
# https://myaccount.google.com/apppasswords
GMAIL_IMAP_SERVER="imap.gmail.com"
GMAIL_IMAP_PORT=993
GMAIL_USERNAME="your-email@gmail.com"
GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
```

### 4. Run System Diagnostics (`doctor`)

Check your environment readiness in one command:

```bash
./faxctl doctor
```

Output:
```
                     🏥 Virtual Fax Gateway - System Doctor                     
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Component                    ┃    Status     ┃ Details                       ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Ghostscript (PDF->TIFF)      │      OK       │ Ghostscript v10.08.0 ready    │
│ Docker Daemon (Asterisk 8YY) │      OK       │ Docker daemon is active.      │
│ Playwright (Web Gateway)     │      OK       │ Playwright Chromium installed │
│ US Egress IP / VPN           │   US REGION   │ Egress IP: 54.187.x.x (AWS US)│
│ Gmail IMAP Auto-Activation   │  CONFIGURED   │ Authenticated with IMAP       │
└──────────────────────────────┴───────────────┴───────────────────────────────┘
```

---

## 💻 CLI Usage Guide

### 1. Send Fax (Auto-Routed)

```bash
# Example 1: Send to IRS Adoption Tax Credit (Toll-Free 855 -> Route A VoIP)
./faxctl send 855-215-1627 /path/to/Form8839.pdf --recipient-name "IRS Adoption Tax Credit"

# Example 2: Send to Alameda County Registrar of Voters (Geographic 510 -> Route B Web)
./faxctl send 510-444-1234 /path/to/VoterReg.pdf --recipient-name "Elections Division"

# Example 3: Dry-run simulation (verifies inputs, formats, and SIP flow without calling)
./faxctl send 855-215-1627 /path/to/Form8839.pdf --dry-run
```

### 2. Inspect Destination Number

Inspect any US number to preview formatting, E.164, SIP dial string, and agency classification:

```bash
./faxctl info 855-822-2694
```

Output:
```
                            🔍 Phone Number Analysis                            
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Property               ┃ Value                                               ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Raw Input              │ 855-822-2694                                        │
│ Display Format         │ +1 (855) 822-2694                                   │
│ 10-Digit Normalization │ 8558222694                                          │
│ E.164 Format           │ +18558222694                                        │
│ SIP Dial String        │ 18558222694                                         │
│ Area Code              │ 855                                                 │
│ Is Toll-Free (8YY)     │ YES                                                 │
│ Default Route          │ VOIP_TOLLFREE                                       │
│ Known Agency           │ Internal Revenue Service (IRS) (ITIN Operations/W-7)│
└────────────────────────┴─────────────────────────────────────────────────────┘
```

### 3. Check Egress IP & US VPN Status

When sending faxes from outside the US, US web portals and certain VoIP trunks require a US egress IP to prevent geolocation rate limits:

```bash
./faxctl check-ip
```

### 4. Test PDF to TIFF Conversion

Test Ghostscript rendering independently:

```bash
./faxctl convert sample.pdf -o output.tif --resolution fine
```

### 5. Verify Gmail IMAP Credentials

```bash
./faxctl test-imap
```

---

## 🐳 Docker Deployment for Route A (Asterisk 20 + SpanDSP)

To run the VoIP Asterisk engine on Linux/EC2 or macOS:

```bash
# Build and start Asterisk in the background
./faxctl docker-up

# Check container logs
docker logs -f fax_asterisk_gateway

# Stop container
./faxctl docker-down
```

### Asterisk Dialplan Details (`extensions.conf`)

When Asterisk originates an outbound call via AMI or a call file, it invokes the `[send-fax]` context:

```ini
[send-fax]
exten => s,1,NoOp(Starting Outbound Fax Transmission to ${RECIPIENT})
same => n,Set(FAXOPT(headerinfo)=${GLOBAL_FAX_HEADER})
same => n,Set(FAXOPT(localstationid)=${GLOBAL_CALLER_ID})
same => n,Set(FAXOPT(maxrate)=14400)
same => n,Set(FAXOPT(minrate)=2400)
same => n,Set(FAXOPT(ecm)=yes)
same => n,Wait(1.5)
same => n,SendFAX(${FAX_FILE},d)
same => n,NoOp(Fax status: ${FAXSTATUS}, error: ${FAXERROR})
same => n,Hangup()
```

---

## 🌐 Running from Outside the US (VPN / EC2 Egress)

When transmitting from outside the United States, you can run the gateway in two production configurations:

### Option A: AWS EC2 Free Tier (`t4g.micro` or `t3.micro` in `us-east-1` / `us-west-2`)
Deploy the repository directly on an AWS EC2 instance in a US region:
1. Launch an Ubuntu 24.04 `t4g.micro` (ARM64) or `t3.micro` instance in `us-east-1` (Eligible for AWS Free Tier).
2. Clone this repo, install requirements, and run `./faxctl send`.
3. The instance naturally has a US public IP address, ensuring 100% gateway acceptance.

### Option B: Local Mac with WireGuard / OpenVPN / Proxy
1. Connect your Mac to a US VPN endpoint (e.g., ProtonVPN Free, Cloudflare WARP US, Tailscale exit node, or private WireGuard VPS).
2. Or configure `HTTP_PROXY="http://us-proxy:8080"` in `.env`.
3. Run `./faxctl check-ip` to confirm `US REGION`.

---

## 🧪 Automated Test Suite

Run the full pytest suite:

```bash
pytest tests/ -v
```

Output:
```
============================== 20 passed in 0.13s ==============================
```

Tests cover:
- NANP phone number parsing, E.164 normalization, and NXX validity rules
- Toll-free classification (`800, 888, 877, 866, 855, 844, 833`)
- PDF inspection and TIFF Class F conversion
- IMAP multipart/HTML email parsing and regex link discovery
- CLI commands, dry-run simulations, and standardized exit codes

---

## 🚦 Standard Exit Codes

The CLI implements UNIX-standard exit codes for integration into automated scripts and CI/CD:

| Code | Constant | Meaning |
|:---:|---|---|
| `0` | `EXIT_SUCCESS` | Fax successfully transmitted / confirmed |
| `1` | `EXIT_INVALID_INPUT` | Malformed phone number, missing PDF, or page limit exceeded |
| `2` | `EXIT_VOIP_FAILURE` | Route A Asterisk / SIP trunk error |
| `3` | `EXIT_WEB_FAILURE` | Route B Playwright web gateway error |
| `4` | `EXIT_IMAP_TIMEOUT` | IMAP email confirmation link not received within timeout |
| `5` | `EXIT_SYSTEM_ERROR` | Missing Ghostscript, Docker, or environment dependencies |

---

## ⚖️ License & Ethical Use

This software is built for transmitting legitimate public documents to government offices, municipal agencies, and election officials. Ensure compliance with federal and state regulations, including the Telephone Consumer Protection Act (TCPA) and terms of service of any third-party relay providers.
