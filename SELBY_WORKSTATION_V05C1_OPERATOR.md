# SELBY Workstation V0.5c.1 — operator instructions

1. Close the older Workstation normally and launch the updated application. Confirm **V0.5c.1** in its title. Keep Windows configured in **French AZERTY**. Keep the TD-W6 in the same US keyboard-output mode used in the reported tests.
2. Open **Scan card**, or press **Ctrl+Shift+S**. Select **TD-W6 US keyboard output → French AZERTY interpretation**. This selection is saved locally and restored on restart. **System keyboard layout** remains the default for profiles not configured yet.
3. Select **Enter / Return suffix** if the scanner sends that suffix. Otherwise choose **No suffix** and click **Identify scan** after each complete scan. Click **Physical scanner input** before scanning; the application focuses it automatically when the dialog opens. Wait for each backend result before scanning another card.
4. Optionally enable **Show last input diagnostic (memory only)**. Scan the existing diagnostic label once. With the previously reported TD-W6 behavior, expect:

   ```text
   Received: 'SELBYMTESTMV&MCQLIBRQTION'
   Validated payload: SELBY:TEST:V1:CALIBRATION
   ```

   The result must say **Diagnostic recognized: CALIBRATION-V1 / TEST / NOT VALID**. Grading must not open. Different raw text may occur with different Caps Lock/device settings; acceptance requires the exact validated diagnostic payload, not an approximation.
5. Scan an existing authorized synthetic physical-card label. Compare the **entire PC reference** in Validated payload and the resolved **ORD, SLB-C and PC** with the known mapping. A payment/inspection block must remain blocked with its existing reasons and no session created. Do not change orders, payment, custody or production mappings to make this test pass.
6. For manual testing, use **Manual QR input / paste**, then Enter or **Identify manual input**. Correct QR text is unchanged under either scanner profile. Pasting `SELBYMTESTMV&MCQLIBRQTION` must fail; manual text is never repaired. Paste is intentionally unavailable in Physical scanner input.
7. If input is rejected, use **Clear scanner input**, confirm the scanner's US output mode and suffix, then scan the whole label again. Missing native key information, unsupported shortcuts, partial frames or invalid QR grammar must not be worked around by guessing a PC. Manual input can troubleshoot the exact canonical payload independently.
8. An immediate repeat is ignored for two seconds, across scanner/manual input after canonical decoding. Wait two seconds to intentionally refresh. Profile selection is disabled during a backend request. The diagnostic shows payload validity only; backend eligibility still controls opening inspection and existing session behavior.
9. Close Scan card to return to ordinary typing. Human typing in Physical scanner input is interpreted as scanner keystrokes because a keyboard wedge shares the keyboard stream. Use the manual field or normal application fields for human input. No Windows layout change is needed.

## Physical acceptance record — pending

No new physical TD-W6 scan was performed during implementation. Complete these operator checks before declaring the profile hardware-validated:

| Check | Record |
| --- | --- |
| Windows remains French AZERTY | Pending |
| TD-W6 connection and US output mode | Pending |
| Real diagnostic scan: received and exact validated payload | Pending |
| Real synthetic card scan: exact PC, ORD and SLB-C | Pending |
| Existing payment reasons remain blocked; no session created | Pending |
| Repeated scan does not duplicate records | Pending |
| Restart restores selected scanner profile | Pending |

The native software tests and screenshots demonstrate the implementation, not physical scanner acceptance. Do not print additional labels or automate physical scans for this procedure.
