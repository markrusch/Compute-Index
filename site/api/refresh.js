// Vercel serverless function: POST /api/refresh?date=YYYY-MM-DD
//
// Triggers daily.yml via workflow_dispatch when (and only when) the requested date is
// today in UTC -- collectors report live market prices, not history, so a past date can
// never be honestly re-collected; this endpoint refuses rather than fake it.
//
// Requires two Vercel environment variables (Project Settings -> Environment Variables,
// never committed to the repo):
//   GITHUB_DISPATCH_TOKEN  a token scoped to just this repo's Actions (read/write),
//                          e.g. a fine-grained PAT limited to markrusch/Compute-Index.
//   GITHUB_REPO            "markrusch/Compute-Index" (owner/repo)
//
// No dependencies: Vercel's Node runtime ships a global fetch.

const WORKFLOW_FILE = "daily.yml";
const RECENT_RUN_WINDOW_MINUTES = 3; // avoid duplicate dispatches from repeated clicks

function todayUtc() {
  return new Date().toISOString().slice(0, 10);
}

async function githubApi(repo, token, path, init) {
  const res = await fetch(`https://api.github.com/repos/${repo}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(init && init.headers),
    },
  });
  return res;
}

module.exports = async (req, res) => {
  if (req.method !== "POST" && req.method !== "GET") {
    res.status(405).json({ ok: false, reason: "method_not_allowed" });
    return;
  }

  const date = (req.query && req.query.date) || todayUtc();
  const today = todayUtc();
  if (date !== today) {
    res.status(400).json({
      ok: false,
      reason: "not_today",
      message:
        "Only today's collection can be requested. Collectors report live market prices, " +
        "not history, so a past date can't be retroactively collected.",
    });
    return;
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPO || "markrusch/Compute-Index";
  if (!token) {
    res.status(500).json({
      ok: false,
      reason: "not_configured",
      message: "Live refresh isn't configured on this deployment (missing dispatch token).",
    });
    return;
  }

  try {
    const runsRes = await githubApi(
      repo,
      token,
      `/actions/workflows/${WORKFLOW_FILE}/runs?per_page=1`
    );
    if (runsRes.ok) {
      const runsBody = await runsRes.json();
      const latestRun = runsBody.workflow_runs && runsBody.workflow_runs[0];
      if (latestRun) {
        const ageMinutes = (Date.now() - new Date(latestRun.created_at).getTime()) / 60000;
        const stillActive = latestRun.status === "in_progress" || latestRun.status === "queued";
        if (stillActive || ageMinutes < RECENT_RUN_WINDOW_MINUTES) {
          res.status(200).json({
            ok: true,
            dispatched: false,
            alreadyRunning: true,
            message: "A collection run is already in progress or just completed.",
            run_url: latestRun.html_url,
          });
          return;
        }
      }
    }

    const dispatchRes = await githubApi(
      repo,
      token,
      `/actions/workflows/${WORKFLOW_FILE}/dispatches`,
      { method: "POST", body: JSON.stringify({ ref: "main" }) }
    );

    if (dispatchRes.status === 204) {
      res.status(200).json({
        ok: true,
        dispatched: true,
        message: "Collection run requested.",
      });
      return;
    }

    const errBody = await dispatchRes.text();
    res.status(502).json({
      ok: false,
      reason: "github_error",
      message: `GitHub API returned ${dispatchRes.status}.`,
      detail: errBody.slice(0, 300),
    });
  } catch (err) {
    res.status(502).json({
      ok: false,
      reason: "github_error",
      message: "Could not reach the GitHub API.",
    });
  }
};
