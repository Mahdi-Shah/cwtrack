"""Build the real approved templates and rebuild their extracted source bundles.

Run manually: python tools/verify_latex_reports.py
Requires XeLaTeX, BibTeX and the template's TeX packages; first use downloads sources.
Outputs are artificial acceptance documents, never coursework or a quality score.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from cwtrack import api, latex_reports


def _body(project: Path, report: bool) -> str:
    image = "front/template/images/logo.png" if report else "images/logo.png"
    (project / "assets").mkdir()
    shutil.copyfile(project / image, project / "assets/sample.png")
    content = r"""
این سند آزمایشی برای بررسی قالب است. عبارت \lr{Sample report} در کنار متن فارسی قرار دارد.
\[
\sum_{k=1}^{n} k = \frac{n(n+1)}{2}
\]
با جایگذاری $n=2$ مقدار دو طرف برابر با $3$ است.
\begin{center}
\begin{tabular}{|c|c|}\hline
ورودی & خروجی \\ \hline
۱ & ۱ \\ ۲ & ۳ \\ \hline
\end{tabular}
\end{center}
\begin{latin}
\begin{lstlisting}[language=Python,breaklines=true]
def total(n):
    return n * (n + 1) // 2
\end{lstlisting}
\end{latin}
\begin{figure}[h]
\centering\includegraphics[width=.1\textwidth]{assets/sample.png}
\caption{نشان موجود در قالب برای بررسی درج تصویر}
\end{figure}
"""
    if report:
        (project / "references.bib").write_text(
            "@misc{template,author={TexReady Group},title={Course Project Report Template},"
            "howpublished={\\url{" + latex_reports.CATALOGUE + "}}}\n", encoding="utf-8")
        content = r"\section{بررسی اجزای گزارش}" + content + r"""
\begin{algorithm}
\caption{جمع اعداد}
\begin{algorithmic}[1]
\Require $n$
\State $s \gets n(n+1)/2$
\State \Return $s$
\end{algorithmic}
\end{algorithm}
منبع قالب در مرجع آمده است \cite{template}.
\newpage
\section{صفحه بعد}
این بخش برای بررسی شکست صفحه و ادامه متن است.
\begin{latin}
\bibliographystyle{plain}
\bibliography{references}
\end{latin}
"""
    else:
        content = content.replace(r"\begin{figure}[h]", r"\begin{center}")
        content = content.replace(r"\caption{نشان موجود در قالب برای بررسی درج تصویر}",
                                  r"\\ نشان موجود در قالب برای بررسی درج تصویر")
        content = content.replace(r"\end{figure}", r"\end{center}")
        content = r"\begin{questions}\question محاسبه جمع\begin{solution}" + content + r"""
\end{solution}
\newpage
\question بررسی صفحه بعد
\begin{solution}
این پاسخ برای بررسی سربرگ و شماره صفحات است.
\end{solution}
\end{questions}
"""
    return content


def verify(output: Path) -> list[dict]:
    data, work = output / "cw-data", output / "work"
    results = []
    for spec in api.report_templates(data=data)["templates"]:
        started = api.work_start({"manual": {"title": "بررسی آزمایشی قالب", "prompt": "ساخت نمونه آزمایشی قالب"}},
                                  data=data, work=work)
        prepared = api.report_prepare(
            started["work_id"], spec["id"],
            {"title": "بررسی آزمایشی گزارش تکلیف", "authors": ["نمونه آزمایشی"],
             "university": "دانشگاه صنعتی شریف", "department": "دانشکده مهندسی کامپیوتر",
             "course": "درس آزمایشی", "term": "نیمسال آزمایشی", "professor": "استاد نمونه"},
            "پذیرش آزمایشی همین قالب؛ این سند پاسخ یک تکلیف واقعی نیست",
            expected_revision=started["revision"], data=data, work=work,
        )
        if prepared["status"] != "ok":
            raise RuntimeError(prepared)
        project = Path(prepared["project"])
        body = _body(project, spec["id"] == "sharif-project-report")
        Path(prepared["content_path"]).write_text(body, encoding="utf-8")
        built = api.report_build(started["work_id"], expected_revision=prepared["revision"],
                                  data=data, work=work, timeout=60)
        if built["status"] != "built":
            raise RuntimeError(built)
        pdf = Path(next(item["path"] for item in built["files"] if item["role"] == "pdf"))
        bundle = Path(next(item["path"] for item in built["files"] if item["role"] == "latex_source"))
        extracted = output / "roundtrip" / started["work_id"]
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(extracted)
        rebuilt = latex_reports.build(extracted, output / "roundtrip-builds", timeout=60)
        if rebuilt["status"] != "built":
            raise RuntimeError(rebuilt)
        if rebuilt["report"]["source_digest"] != built["report"]["source_digest"]:
            raise RuntimeError("Extracted sources do not match original build inputs")
        previews = output / "previews" / spec["id"]
        previews.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pdftoppm", "-scale-to", "1100", "-png", str(pdf), str(previews / "page")], check=True)
        subprocess.run(["pdftotext", "-layout", str(pdf), str(previews / "text.txt")], check=True)
        result = {"template_id": spec["id"], "status": "built_and_source_rebuilt",
                  "work_id": started["work_id"], "pdf": str(pdf), "source": str(bundle),
                  "previews": str(previews), "source_digest": built["report"]["source_digest"]}
        results.append(result)
        output.mkdir(parents=True, exist_ok=True)
        (output / "acceptance.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(spec["id"] + ": built, source archive rebuilt, pages rendered", flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/latex-template-acceptance"))
    args = parser.parse_args()
    verify(args.output.resolve())
