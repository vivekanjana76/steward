import { ActivityStream } from "@/components/ActivityStream";
import { ApprovalQueue } from "@/components/ApprovalQueue";
import { Scorecard } from "@/components/Scorecard";
import { StatRail } from "@/components/StatRail";
import { TopBar } from "@/components/TopBar";
import { API_BASE, loadDashboard } from "@/lib/steward";

// The audit log + approval queue are live state — never cache the page.
export const dynamic = "force-dynamic";

function OfflineNotice() {
  return (
    <div className="glass rounded-2xl border-rose-400/20 px-5 py-4">
      <p className="text-sm text-slate-200">
        <span className="font-semibold text-rose-300">Steward core is offline.</span> The
        dashboard is up, but it can&apos;t reach the API.
      </p>
      <p className="mt-1 font-mono text-[11px] text-slate-500">
        Start it with <span className="text-cyan-300">just api</span> (optionally{" "}
        <span className="text-cyan-300">STEWARD_SEED_DEMO=true</span>) and confirm{" "}
        <span className="text-cyan-300">{API_BASE}</span> is reachable.
      </p>
    </div>
  );
}

export default async function Page() {
  const { online, health, actions, approvals, scorecard } = await loadDashboard();

  return (
    <div className="min-h-screen">
      <TopBar health={health} online={online} />

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
        <section className="space-y-2">
          <h1 className="font-display text-2xl font-semibold tracking-tight text-slate-100 sm:text-3xl">
            What Steward did{" "}
            <span className="bg-gradient-to-r from-cyan-300 to-violet-300 bg-clip-text text-transparent">
              this week
            </span>
          </h1>
          <p className="max-w-2xl text-sm text-slate-400">
            Every action is classified by the policy engine, gated by a human for anything
            that mutates the world, and written to a tamper-evident audit log. Nothing here
            is a claim without evidence.
          </p>
        </section>

        {!online && <OfflineNotice />}

        <StatRail actions={actions} approvals={approvals} />

        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ActivityStream actions={actions} />
          </div>
          <div className="lg:col-span-1">
            <ApprovalQueue approvals={approvals} />
          </div>
        </div>

        <Scorecard scorecard={scorecard} />

        <footer className="hairline flex flex-col items-center justify-between gap-2 pt-6 pb-4 text-center sm:flex-row sm:text-left">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-600">
            Steward · autonomous maintainer&apos;s teammate
          </p>
          <p className="font-mono text-[10px] text-slate-600">
            whitelist allow · greylist approve · blacklist deny — always
          </p>
        </footer>
      </main>
    </div>
  );
}
