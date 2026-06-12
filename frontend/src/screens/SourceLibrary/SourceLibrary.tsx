// Screen 7 — Source library. Table with relevance + credibility, triage
// status + reason, discovery channel; diversity indicator; filters/sort;
// promote/exclude/add-manually overrides that round-trip to the backend;
// drill-in to Paper Analysis Detail.

import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useAddSource, useSourceOverride, useSources } from "../../api/hooks";
import type { DiscoveryChannel, Source, TriageStatus } from "../../api/types";
import {
  Badge,
  Button,
  Callout,
  Card,
  ConfidenceMeter,
  Icon,
  Input,
  Select,
  type BadgeTone,
} from "../../components/ds";
import { authorsLine } from "../../components/helpers";
import { EmptyState } from "../../components/shared";

const TRIAGE_META: Record<TriageStatus, { label: string; tone: BadgeTone }> = {
  deep_read: { label: "Deep read", tone: "accent" },
  skimmed: { label: "Skimmed", tone: "info" },
  set_aside: { label: "Set aside", tone: "neutral" },
  excluded: { label: "Excluded", tone: "danger" },
};

const CHANNEL_META: Record<DiscoveryChannel, { label: string; icon: string }> = {
  keyword_search: { label: "Keyword search", icon: "search" },
  citation_snowball: { label: "Citation snowball", icon: "git-branch" },
  user_supplied: { label: "You added this", icon: "user" },
};

type SortKey = "relevance" | "credibility" | "year" | "title";

function AddSourceForm({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const add = useAddSource(projectId);
  const [title, setTitle] = useState("");
  const [doi, setDoi] = useState("");
  const [url, setUrl] = useState("");
  return (
    <Card pad className="addsource">
      <h4>Add a source manually</h4>
      <div className="form-grid">
        <Input label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Input
          label="DOI"
          value={doi}
          onChange={(e) => setDoi(e.target.value)}
          placeholder="optional"
        />
        <Input
          label="URL"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="optional"
        />
      </div>
      <div className="form-actions">
        <Button
          size="sm"
          disabled={title.trim().length < 3 || add.isPending}
          onClick={async () => {
            await add.mutateAsync({ title: title.trim(), doi: doi || null, url: url || null });
            setTitle("");
            setDoi("");
            setUrl("");
            onDone();
          }}
        >
          Add and queue for deep read
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}

function Row({ source, projectId }: { source: Source; projectId: string }) {
  const override = useSourceOverride(projectId);
  const triage = source.triage_status ? TRIAGE_META[source.triage_status] : null;
  const channel = source.discovery_channel ? CHANNEL_META[source.discovery_channel] : null;
  return (
    <div className="source-row" data-testid={`source-row-${source.id}`}>
      <div className="source-row__main">
        <Link to={`/projects/${projectId}/sources/${source.id}`} className="source-row__title">
          {source.title}
        </Link>
        <span className="source-row__meta">
          {authorsLine(source.authors)}
          {source.year ? ` · ${source.year}` : ""}
          {source.venue ? ` · ${source.venue}` : ""}
        </span>
        {source.triage_reason && <span className="source-row__reason">{source.triage_reason}</span>}
      </div>
      <span className="source-row__score">
        {source.relevance_score != null ? (
          <>
            <ConfidenceMeter value={source.relevance_score} showLabel={false} />
            <span className="source-row__pct">{Math.round(source.relevance_score * 100)}%</span>
          </>
        ) : (
          "—"
        )}
      </span>
      <span className="source-row__score">
        {source.credibility_score != null ? (
          <>
            <ConfidenceMeter value={source.credibility_score} showLabel={false} />
            <span className="source-row__pct">{Math.round(source.credibility_score * 100)}%</span>
          </>
        ) : (
          "—"
        )}
      </span>
      <span>{triage && <Badge tone={triage.tone}>{triage.label}</Badge>}</span>
      <span className="source-row__channel">
        {channel && (
          <>
            <Icon name={channel.icon} size={14} /> {channel.label}
          </>
        )}
      </span>
      <span className="source-row__actions">
        {source.triage_status !== "deep_read" && (
          <Button
            variant="ghost"
            size="sm"
            iconLeft="arrow-up"
            title="Promote to deep read — may re-trigger analysis"
            onClick={() => override.mutate({ sourceId: source.id, body: { action: "promote" } })}
          >
            Promote
          </Button>
        )}
        {source.triage_status !== "excluded" && (
          <Button
            variant="ghost"
            size="sm"
            iconLeft="x"
            title="Exclude from the research"
            onClick={() => override.mutate({ sourceId: source.id, body: { action: "exclude" } })}
          >
            Exclude
          </Button>
        )}
      </span>
    </div>
  );
}

export function SourceLibrary() {
  const { projectId } = useParams<{ projectId: string }>();
  const [q, setQ] = useState("");
  const [triage, setTriage] = useState("");
  const [channel, setChannel] = useState("");
  const [sort, setSort] = useState<SortKey>("relevance");
  const [adding, setAdding] = useState(false);

  const sources = useSources(projectId, {
    q: q || undefined,
    triage_status: triage || undefined,
    discovery_channel: channel || undefined,
  });

  const items = useMemo(() => {
    const list = [...(sources.data?.items ?? [])];
    list.sort((a, b) => {
      if (sort === "title") return a.title.localeCompare(b.title);
      if (sort === "year") return (b.year ?? 0) - (a.year ?? 0);
      if (sort === "credibility") return (b.credibility_score ?? 0) - (a.credibility_score ?? 0);
      return (b.relevance_score ?? 0) - (a.relevance_score ?? 0);
    });
    return list;
  }, [sources.data, sort]);

  // Diversity / echo-chamber heuristic: share discovered via a single channel.
  const all = sources.data?.items ?? [];
  const channelCounts = all.reduce<Record<string, number>>((acc, s) => {
    const c = s.discovery_channel ?? "unknown";
    acc[c] = (acc[c] ?? 0) + 1;
    return acc;
  }, {});
  const included = all.filter((s) => s.triage_status !== "excluded");
  const dominant = Object.entries(channelCounts).sort((a, b) => b[1] - a[1])[0];
  const echoChamber = included.length >= 8 && dominant && dominant[1] / included.length > 0.85;

  return (
    <div className="screen">
      <header className="screen-head screen-head--row">
        <div>
          <div className="eyebrow">Source library</div>
          <h1 className="screen-title">Sources</h1>
          <p className="screen-sub">
            {all.length} found · {all.filter((s) => s.triage_status === "deep_read").length}{" "}
            deep-read · {all.filter((s) => s.triage_status === "excluded").length} excluded
          </p>
        </div>
        <Button variant="secondary" iconLeft="plus" onClick={() => setAdding(true)}>
          Add source
        </Button>
      </header>

      {echoChamber && (
        <Callout tone="warning" title="Possible echo chamber">
          {Math.round((dominant![1] / included.length) * 100)}% of included sources came from one
          discovery channel ({dominant![0].replace("_", " ")}). Consider adding sources manually or
          widening the scope.
        </Callout>
      )}

      {adding && projectId && (
        <AddSourceForm projectId={projectId} onDone={() => setAdding(false)} />
      )}

      <div className="dash-filters">
        <Input
          icon="search"
          placeholder="Search title, venue, abstract…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Select
          aria-label="Filter by triage"
          value={triage}
          onChange={(e) => setTriage(e.target.value)}
          options={[
            { value: "", label: "All triage states" },
            { value: "deep_read", label: "Deep read" },
            { value: "skimmed", label: "Skimmed" },
            { value: "set_aside", label: "Set aside" },
            { value: "excluded", label: "Excluded" },
          ]}
        />
        <Select
          aria-label="Filter by channel"
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
          options={[
            { value: "", label: "All channels" },
            { value: "keyword_search", label: "Keyword search" },
            { value: "citation_snowball", label: "Citation snowball" },
            { value: "user_supplied", label: "User supplied" },
          ]}
        />
        <Select
          aria-label="Sort sources"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          options={[
            { value: "relevance", label: "By relevance" },
            { value: "credibility", label: "By credibility" },
            { value: "year", label: "By year" },
            { value: "title", label: "By title" },
          ]}
        />
      </div>

      {sources.isLoading && <p className="muted-note">Loading sources…</p>}

      {!sources.isLoading && items.length === 0 && (
        <EmptyState title="No sources yet">
          The literature search fills this library as it runs; you can also add sources yourself.
        </EmptyState>
      )}

      {items.length > 0 && (
        <Card className="source-table">
          <div className="source-row source-row--head">
            <span>Source</span>
            <span>Relevance</span>
            <span>Credibility</span>
            <span>Triage</span>
            <span>Discovered via</span>
            <span />
          </div>
          {items.map((s) => (
            <Row key={s.id} source={s} projectId={projectId!} />
          ))}
        </Card>
      )}
    </div>
  );
}
