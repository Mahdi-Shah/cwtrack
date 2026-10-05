# Third-party licenses

The MIT terms in [LICENSE](LICENSE) cover this project's own code only. The fonts
below are redistributed as binary files and carry their own licences.

## Estedad

- **File:** `src/cwtrack/fonts/Estedad-VF.ttf`
- **Licence:** SIL Open Font License 1.1
- **Copyright:** the Estedad authors — see the font's own metadata table
- **Why it is here:** the dashboard's Persian UI face. It is a variable font
  (weight axis 100–900), so one file covers every weight the stylesheet asks for.
- **Full text:** https://openfontlicense.org

## Vazirmatn

- **Files:** `src/cwtrack/fonts/Vazirmatn-{Regular,Bold}.ttf`,
  `.agents/skills/university-assignment/assets/fonts/Vazirmatn-{Regular,Medium,Bold}.ttf`
- **Licence:** SIL Open Font License 1.1
- **Copyright:** the Vazirmatn authors — Saber Rastikerdar and contributors
- **Why it is here:** the PDF renderer embeds it, and it is the fallback face for the
  dashboard when the variable font is unavailable.
- **Full text:** https://openfontlicense.org

## What the OFL requires, and what that means here

The SIL OFL permits bundling and redistribution, including inside a commercial
product. Two conditions matter in practice:

- **The fonts may not be sold on their own.** They are shipped as part of a tool,
  which the OFL permits; selling `Vazirmatn-Regular.ttf` by itself would not.
- **The licence must travel with the files.** That is what this document is for.

Renaming or modifying the fonts would require renaming the derived files, which is
why they are redistributed under their original names and unmodified.

## Fonts are deliberately not in the wheel's dependency graph

They are package data, inside the package, declared in
`[tool.setuptools.package-data]`. That is deliberate for two reasons:

1. Installing the tool cannot disturb a student's existing environment.
2. A wheel built without them still installs and still runs — it just renders the
   dashboard in Tahoma, with no error anywhere. CI checks for their presence rather
   than trusting the build to be complete.