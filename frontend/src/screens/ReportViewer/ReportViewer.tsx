// Screen 11 — Report viewer. Rendered markdown with inline confidence badges
// and citation markers that open the provenance overlay; self-check result;
// stopping-criterion note; edit (PATCH), rewrite-for-audience/expand, and
// docx/md export.

import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { usePatchReport, useProvenance, useReports, useRewriteReport } from "../../api/hooks";
import { api } from "../../api/client";
import { Badge, Button, Callout, Card, Select } from "../../components/ds";
import { CitedMarkdown, citedSourceIds } from "../../components/CitedMarkdown";
import { useProvenanceTrace } from "../../components/ProvenancePopover";
import { EmptyState } from "../../components/shared";

export function ReportViewer() {
  const { projectId } = useParams<{ projectId: string }>();
  const reports = useReports(projectId);
  const patchReport = usePatchReport();
  const rewrite = useRewriteReport();
  const { openTrace } = useProvenanceTrace();

  const [version, setVersion] = useState<string>("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [rewriteAudience, setRewriteAudience] = useState("");
  const [rewriteLength, setRewriteLength] = useState("");

  const list = reports.data ?? [];
  const report = version ? list.find((r) => r.id === version) : list[0];

  const provenance = useProvenance(
    projectId,
    { ref_id: report?.id, context: "report" },
    !!report,
  );

  const numbering = useMemo(() => {
    const map = new Map<string, number>();
    if (report?.content_markdown) {
      citedSourceIds(report.content_markdown).forEach((id, i) => map.set(id, i + 1));
    }
    return map;
  }, [report?.content_markdown]);

  if (reports.isLoading) return <p className="muted-note screen">Loading report…</p>;

  if (!report) {
    return (
      <div className="screen">
        <EmptyState icon="book-open" title="No report yet">
          The report is written after gap analysis completes; it appears here with every claim
          cited.
        </EmptyState>
      </div>
    );
  }

  const onCite = (sourceId: string) => {
    const rows = (provenance.data ?? []).filter((p) => p.source_id === sourceId);
    openTrace({
      projectId: projectId!,
      rows: rows.length > 0 ? rows : undefined,
      refId: rows.length > 0 ? undefined : report.id,
      sourceId,
    });
  };

  const selfCheck = report.self_check_result;
  const findings = (selfCheck?.findings ?? []) as { issue?: string; action?: string; note?: string }[];

  const saveEdit = async () => {
    await patchReport.mutateAsync({ reportId: report.id, content: draft });
    setEditing(false);
    setVersion("");
  };

  const doRewrite = async () => {
    await rewrite.mutateAsync({
      reportId: report.id,
      body: {
        audience: rewriteAudience || null,
        length: (rewriteLength || null) as "brief" | "standard" | "comprehensive" | null,
      },
    });
    setVersion("");
  };

  return (
    <div className="screen screen--reading">
      <header className="screen-head screen-head--row">
        <div>
          <div className="eyebrow">Report · v{report.version}</div>
          <h1 className="screen-title">Research report</h1>
          <div className="report-meta">
            {report.audience && <Badge tone="neutral">audience: {report.audience}</Badge>}
            {report.stopping_criterion && (
              <Badge
                tone={report.stopping_criterion === "budget" ? "warning" : "neutral"}
                data-testid="stopping-criterion"
              >
                stopped by: {report.stopping_criterion.replace(/_/g, " ")}
              </Badge>
            )}
          </div>
        </div>
        <div className="screen-head__side report-toolbar">
          {list.length > 1 && (
            <Select
              aria-label="Report version"
              value={report.id}
              onChange={(e) => setVersion(e.target.value)}
              options={list.map((r) => ({ value: r.id, label: `v${r.version}` }))}
            />
          )}
          <Button
            variant="secondary"
            size="sm"
            iconLeft="pencil"
            onClick={() => {
              setDraft(report.content_markdown ?? "");
              setEditing(true);
            }}
          >
            Edit
          </Button>
          <a href={api.reportExportUrl(report.id, "docx")} download>
            <Button variant="secondary" size="sm" iconLeft="download">
              .docx
            </Button>
          </a>
          <a href={api.reportExportUrl(report.id, "md")} download>
            <Button variant="ghost" size="sm" iconLeft="download">
              .md
            </Button>
          </a>
        </div>
      </header>

      {selfCheck && (
        <Callout
          tone={findings.length > 0 ? "warning" : "insight"}
          title={
            findings.length > 0
              ? `Self-check: ${findings.length} claim(s) were revised before this report was finalized`
              : "Self-check passed — every claim is grounded or flagged"
          }
          data-testid="self-check"
        >
          {typeof selfCheck.summary === "string" && selfCheck.summary}
          {findings.length > 0 && (
            <ul>
              {findings.slice(0, 6).map((f, i) => (
                <li key={i}>
                  <strong>{f.issue?.replace(/_/g, " ")}</strong> → {f.action?.replace(/_/g, " ")}
                  {f.note ? ` — ${f.note}` : ""}
                </li>
              ))}
            </ul>
          )}
        </Callout>
      )}

      {editing ? (
        <Card pad>
          <textarea
            className="kw-input report-editor"
            rows={24}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="Report markdown"
          />
          <div className="form-actions">
            <Button onClick={saveEdit} disabled={patchReport.isPending}>
              {patchReport.isPending ? "Saving…" : "Save as new version"}
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </Card>
      ) : (
        <article className="report-body" data-testid="report-body">
          <CitedMarkdown
            markdown={report.content_markdown ?? "*This report version has no content.*"}
            numbering={numbering}
            onCite={onCite}
          />
        </article>
      )}

      <Card pad className="report-rewrite">
        <h4>Rewrite</h4>
        <p className="muted-note">
          Re-pitch the report for a different audience or length; the original version is kept.
        </p>
        <div className="form-grid">
          <Select
            label="Audience"
            value={rewriteAudience}
            onChange={(e) => setRewriteAudience(e.target.value)}
            options={[
              { value: "", label: "Keep current" },
              { value: "domain_expert", label: "Domain expert" },
              { value: "executive", label: "Executive" },
              { value: "general", label: "General reader" },
            ]}
          />
          <Select
            label="Length"
            value={rewriteLength}
            onChange={(e) => setRewriteLength(e.target.value)}
            options={[
              { value: "", label: "Keep current" },
              { value: "brief", label: "Brief" },
              { value: "standard", label: "Standard" },
              { value: "comprehensive", label: "Comprehensive" },
            ]}
          />
        </div>
        <div className="form-actions">
          <Button
            variant="secondary"
            size="sm"
            disabled={(!rewriteAudience && !rewriteLength) || rewrite.isPending}
            onClick={doRewrite}
          >
            {rewrite.isPending ? "Rewriting…" : "Rewrite"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
