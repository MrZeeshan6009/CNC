# Judge Demo Runbook

## Colab

1. Open Google Colab and upload `dist/CNC_Part_Analyzer_Colab.ipynb`.
2. Select a CPU runtime.
3. Run cell 1 and wait for `Setup complete`.
4. Run cell 2 and enter the DeepSeek key. The input is hidden.
5. Run cell 3 and leave it running.
6. Share the printed `Judge URL` or `Demo URL`.

The notebook downloads the application from the public GitHub repository. It contains
no embedded project or API key; no project ZIP, Docker image, or GPU is required.

## Two-minute demonstration

1. Click **Run demo**.
2. Show part `2280`: all three sources agree.
3. Select `A-2281`: the drawing and CAD length conflict.
4. Select `3300`: CAD is missing, so the result is incomplete rather than a conflict.
5. Open **Ask DeepSeek** and click **What are the dimensions?**
6. Point out the validated evidence citations in the answer.

## If Colab stops

- Run cells 1–3 again. A new public URL will be printed.
- Keep the final cell and the Colab tab open during judging.
- Keep the local app available at `http://127.0.0.1:8501/?dataset=demo` as backup.

## Expected results

| Part | Result |
| --- | --- |
| `2280` | Consistent |
| `A-2281` | Conflict |
| `3300` | Incomplete |
