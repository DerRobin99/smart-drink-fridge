# Android closed test

**Status, 24 October 2026:** Google has approved Android 1.0.0 and the closed Alpha test is live. Join the group and opt in below to access the Play installation link. This is not a public production release.

We are looking for 15–20 volunteers who would use Smart Drink Fridge on Android and tell us what works or gets in the way. The app is free and has no ads.

## Join the test

1. [Join the tester Google Group](https://groups.google.com/g/smart-drink-fridge-android-testers) with the Google account you use for Play. Choose **Join group**; email delivery can be set to **No email**. Membership is voluntary and the member list is restricted to the group owner.
2. Opt in and install using the steps below. Group membership alone does not enroll you in the Play test.

If joining does not work, email [mail@calmbike.de](mailto:mail@calmbike.de?subject=Smart%20Drink%20Fridge%20Android%20test). **Do not post your Google email address in a public issue or Reddit comment.**

After joining the group:

1. Sign in with the same Google account you use in the Play Store.
2. Open the [Google Play tester opt-in page](https://play.google.com/apps/testing/de.derrobin99.smartdrinkfridge) and accept the invitation to become a tester.
3. Follow the installation link on that page.
4. Please stay opted in for at least 14 consecutive days and try the app during normal use. Joining an access group alone does not start your Play opt-in period.

If the link is unavailable, check that the Google Group, tester opt-in page and Play Store all use the same Google account. Group posting permissions do not affect installation access. If Play still cannot download the app, send the exact error, phone model and Android version; do not post your account email publicly. There is no APK to sideload for this test.

## What you need

- An Android phone running Android 9 or newer, with Google Play.
- This test is intended for adults (18+).
- For the full workflow, your own Smart Drink Fridge server and its login details, reachable over HTTPS. See the [installation guide](https://github.com/DerRobin99/smart-drink-fridge/wiki/Installation) and [security guide](https://github.com/DerRobin99/smart-drink-fridge/wiki/Security). Keep the Flask service off the public internet.
- The built-in offline preview lets you explore without a server, but does not exercise live inventory or bookings. Please mention whether you tested preview mode or a real server.

## Things to try

- Connect to your server, sign in, close and reopen the app.
- Browse inventory and check that quantities agree with the web interface.
- Scan a drink barcode with the camera, then try manual entry too.
- Book a drink and check the updated stock and history.
- Open statistics and the shopping list.
- Try an interrupted connection and tell us whether recovery is clear.

Use a test inventory if you want to experiment without changing your household stock.

## Send feedback

Open a [GitHub issue](https://github.com/DerRobin99/smart-drink-fridge/issues/new/choose), or email [mail@calmbike.de](mailto:mail@calmbike.de). English and German are both welcome.

Useful details: phone model, Android version, app version, server version, what you tried, what you expected and what happened. Screenshots help, but remove passwords, tokens, private server addresses and personal data first. Honest feedback is the goal; no positive rating is requested.

Google requires this developer account to complete a closed test with at least 12 people opted in continuously for 14 days before applying for production access. Real testing and feedback also matter. Meeting the minimum does not guarantee approval, and there is no fixed public release date yet.

[Android app privacy policy](android-app-privacy-policy.md)
