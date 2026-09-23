export const meta = {
  name: 'ai-enrich',
  description: 'Propose and check German or English words and definitions for a slice of ReVo articles',
  whenToUse: 'Run with the args slice.py prints (revo-fonto ai-enrich/README.md).',
  phases: [
    { title: 'Propose', detail: 'ai-propose: definitions and words per article, saved by ask.py' },
    { title: 'Check', detail: 'ai-check: a verdict on every proposal, saved by ask.py' },
  ],
}

// args: what slice.py prints: {root, lng, holdout, run, model, bundles: [[article, ...], ...]}, plus
// optionally typed: false when the session does not know the ai-propose/ai-check agent types (they
// load at session start); the default workflow agent then runs, held to ask.py by the prompt alone.
// Each agent saves its own result per article through ask.py, so nothing lives only in this run;
// what an agent returns is a receipt, and the check stage takes only the articles saved before it.
const { root, lng, holdout, run, model, bundles, typed = true } = args
const type = (t) => (typed ? { agentType: t } : {})
const where = holdout ? `out/${lng}/holdout` : `out/${lng}`
const flag = holdout ? ' --holdout' : ''

const RECEIPT = {
  type: 'object',
  required: ['saved', 'failed'],
  properties: {
    saved: { type: 'array', items: { type: 'string' }, description: 'articles saved ("Saved" from ask.py)' },
    failed: {
      type: 'array',
      items: { type: 'object', required: ['article', 'reason'], properties: { article: { type: 'string' }, reason: { type: 'string' } } },
    },
  },
}

const task = (stage, articles) => [
  `Read ${root}/ai-enrich/prompt-${stage}.md and follow it exactly.`,
  `Target language: ${lng}. Run tag: ${run}. Model: ${model}.${holdout ? ' This is a holdout run.' : ''}`,
  `Work in ${root}: start every command with \`cd ${root} && \`.`,
  `Handle these articles one after another, each on its own, and save each before starting the next:`,
  ...articles.map((a) => `- ${a}: work file ${root}/ai-enrich/${where}/work/${a}.json` +
    (stage === 'check' ? `, proposals ${root}/ai-enrich/${where}/results/${a}.propose.json` : '') +
    `; save with \`cd ${root} && python3 ai-enrich/ask.py save ${stage} ${lng} ${a} --run ${run} --model ${model}${flag} <<'JSON'\``),
  `Return which articles you saved and which you could not, with the reason.`,
].join('\n')

// agents sometimes add a note to a name ("ajn: definitions 2, ...", "Saved out/de/results/ajn.check.json"):
// an article counts when its name starts the entry or follows a slash
const named = (receipt, articles) => articles.filter((a) =>
  (receipt?.saved ?? []).some((s) => s === a || new RegExp(`(^|/)${a}\\b`).test(s.trim())))

const results = await pipeline(
  bundles,
  (articles, _, i) => agent(task('propose', articles), {
    label: `propose ${i + 1}: ${articles.join(' ')}`, phase: 'Propose', ...type('ai-propose'), schema: RECEIPT,
  }),
  (proposed, articles, i) => {
    const saved = named(proposed, articles)
    const missing = articles.filter((a) => !saved.includes(a))
    if (missing.length) log(`propose ${i + 1}: not saved: ${missing.join(' ')}`)
    if (!saved.length) return { articles, proposed, checked: null }
    return agent(task('check', saved), {
      label: `check ${i + 1}: ${saved.join(' ')}`, phase: 'Check', ...type('ai-check'), schema: RECEIPT,
    }).then((checked) => {
      log(`bundle ${i + 1} checked (${saved.length} articles); ${budget.spent()} output tokens this turn so far`)
      return { articles, proposed, checked }
    })
  },
)

const all = results.filter(Boolean)
const checked = all.flatMap((r) => (r.checked ? named(r.checked, r.articles) : []))
const failed = all.flatMap((r) => [...(r.proposed?.failed ?? []), ...(r.checked?.failed ?? [])])
return {
  lng, holdout, run,
  bundles: bundles.length,
  articles: bundles.flat().length,
  checked: checked.length,
  not_checked: bundles.flat().filter((a) => !checked.includes(a)),
  failed,
  output_tokens: budget.spent(),
}
