# Legal Notice

## Trademarks

**Batmobile™**, **Justice League™**, **Batman™**, and related marks and
characters are trademarks of DC Comics, an imprint of DC Entertainment Inc.,
a subsidiary of Warner Bros. Discovery.

**Mattel®** and **Hot Wheels®** are registered trademarks of Mattel, Inc.

This project is **not affiliated with, endorsed by, sponsored by, or
authorized by** Mattel, DC Comics, Warner Bros. Discovery, or any of their
subsidiaries or affiliates. The names are used solely to identify the
specific consumer hardware product (Mattel SKU **FKM40** — *Justice League
Ultimate Batmobile R/C, 1/10 scale*) that this project re-enables.

## Reverse engineering

This project documents the WiFi control protocol exposed by the Mattel FKM40
toy. It does **not**:

- redistribute the original Mattel APK or any portion of it
- bypass any access controls (the toy's WiFi AP is unencrypted to the owner;
  the default WPA2-PSK key is published in the toy's setup documentation)
- decode or redistribute any DRM-protected content
- use any of Mattel's proprietary code, art, or branding in the controller
  itself

The protocol was reverse-engineered by static analysis of the publicly
available Android APK (last published version 1.3.1). The APK was obtained
from public mirror sites *after* Mattel removed it from the Google Play
Store on **15 March 2024**, leaving owners of the toy without a functional
controller.

## Right to repair

This project exists because Mattel discontinued support for a consumer
product that owners had paid for. The official **Batmobile™ R/C Controller**
Android app was unpublished from Google Play on 15 March 2024. iOS support
ended earlier. Mattel customer service has confirmed no replacement is
planned.

The U.S. Library of Congress, in its triennial DMCA Section 1201
rulemaking, has granted exemptions for owners of consumer electronics to
modify or repair devices they own when the manufacturer has discontinued
support. (See 37 CFR § 201.40, most recently renewed 2024.)

This project relies on those exemptions and on equivalent right-to-repair
provisions in your jurisdiction. **You are responsible for compliance with
local law.**

## Use restrictions

- Do **not** use this software to control hardware you do not own.
- Do **not** use the project name, branding, or implementation to imply
  affiliation with Mattel, DC Comics, or Warner Bros.
- Commercial resale of pre-flashed Pi units paired with the toy is
  permitted under the MIT license, but any product packaging must include
  this notice and must not use the trademarks above as primary branding.

## Reporting

If you are a rights holder and believe this project crosses a legal line
that the disclaimers and law above do not adequately address, please open
a GitHub issue or email **legal@salient-concepts.com** before any takedown
action — most concerns can be resolved with a small change.
