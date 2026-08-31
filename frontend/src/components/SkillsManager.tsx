import { useCallback, useEffect, useState } from "react";
import { deleteSkill, getSkill, installSkill, listSkills, patchSkill } from "../net/api";
import type { SkillDetail, SkillSummary, SkillTier } from "../store/types";
import "./SkillsManager.css";

const TIERS: { tier: SkillTier; label: string; empty: string }[] = [
  { tier: "built-in", label: "Built-in", empty: "No built-in skills shipped." },
  { tier: "org", label: "Organization", empty: "No organization skills installed." },
  { tier: "user", label: "Your skills", empty: "No personal skills yet — install one above." },
];

const NEW_SKILL_TEMPLATE = `---
name: my-skill
description: What this skill does and when the agent should use it.
---

# My Skill

Step-by-step instructions the agent follows when this skill activates.
`;

function SkillCard({ skill, onChanged }: { skill: SkillSummary; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const untrusted = skill.trust_state !== "trusted";
  const builtin = skill.tier === "built-in";

  const toggleExpand = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !detail) setDetail(await getSkill(skill.skill_id));
  };

  const scripts = skill.file_names.filter((f) => f.startsWith("scripts/"));
  const bundled = skill.file_names.filter((f) => !f.startsWith("scripts/"));

  return (
    <div className={`da-skillcard ${skill.enabled ? "" : "is-off"}`}>
      <div className="da-skillcard-head">
        <button
          className="da-skillcard-name"
          onClick={() => void toggleExpand()}
          aria-expanded={expanded}
        >
          <span className="da-skillcard-caret">{expanded ? "▾" : "▸"}</span>
          {skill.name}
        </button>
        {untrusted ? (
          <span className="da-chip da-chip-warn">needs review</span>
        ) : (
          <span className="da-chip da-chip-ok">trusted</span>
        )}
        <span className="da-skillcard-source">{skill.source}</span>
        <button
          role="switch"
          aria-checked={skill.enabled}
          aria-label={`${skill.enabled ? "Disable" : "Enable"} ${skill.name}`}
          className={`da-toggle ${skill.enabled ? "is-on" : ""}`}
          disabled={untrusted}
          title={untrusted ? "Review this skill before enabling it" : undefined}
          onClick={async () => {
            await patchSkill(skill.skill_id, { enabled: !skill.enabled });
            onChanged();
          }}
        >
          <span className="da-toggle-knob" />
        </button>
      </div>
      <p className="da-skillcard-desc">{skill.description}</p>
      {expanded && (
        <div className="da-skillcard-body">
          {untrusted && (
            <div className="da-skillcard-review">
              Read the instructions below, then
              <button
                className="da-skillbtn"
                onClick={async () => {
                  await patchSkill(skill.skill_id, { trust_state: "trusted" });
                  onChanged();
                }}
              >
                Mark reviewed
              </button>
            </div>
          )}
          <pre className="da-skillcard-md">{detail ? detail.body : "Loading…"}</pre>
          {(bundled.length > 0 || scripts.length > 0) && (
            <div className="da-skillcard-files">
              {bundled.map((f) => (
                <span key={f} className="da-chip">{f}</span>
              ))}
              {scripts.map((f) => (
                <span key={f} className="da-chip da-chip-locked" title="Script execution is disabled">
                  🔒 {f} · exec off · v1
                </span>
              ))}
            </div>
          )}
          {!builtin && (
            <div className="da-skillcard-actions">
              {!confirmDelete ? (
                <button className="da-skillbtn is-danger" onClick={() => setConfirmDelete(true)}>
                  Delete
                </button>
              ) : (
                <>
                  <button
                    className="da-skillbtn is-danger"
                    onClick={async () => {
                      await deleteSkill(skill.skill_id);
                      onChanged();
                    }}
                  >
                    Confirm delete
                  </button>
                  <button className="da-skillbtn" onClick={() => setConfirmDelete(false)}>
                    Cancel
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function SkillsManager() {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [draftTier, setDraftTier] = useState<"user" | "org">("user");
  const [formError, setFormError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listSkills().then(setSkills).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const openForm = (template: string) => {
    setDraft(template);
    setFormError(null);
    setFormOpen(true);
  };

  const submitInstall = async () => {
    setFormError(null);
    const result = await installSkill(draft, draftTier);
    if (typeof result === "string") {
      setFormError(result);
      return;
    }
    setFormOpen(false);
    setDraft("");
    refresh();
  };

  return (
    <div className="da-skills">
      <div className="da-skills-inner">
        <div className="da-skills-head">
          <h2>Skills</h2>
          <div className="da-skills-actions">
            <button className="da-skillbtn" onClick={() => openForm("")}>Install</button>
            <button className="da-skillbtn is-primary" onClick={() => openForm(NEW_SKILL_TEMPLATE)}>
              New skill
            </button>
          </div>
        </div>
        <p className="da-skills-note">
          Skills are instruction files the agent reads when a task matches (agentskills.io format).
          New installs stay off until reviewed; changes apply to new chats.
        </p>

        {formOpen && (
          <div className="da-skills-form">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Paste a SKILL.md — YAML frontmatter (name, description) followed by instructions."
              spellCheck={false}
            />
            {formError && <div className="da-skills-error">{formError}</div>}
            <div className="da-skills-form-row">
              <label>
                Tier{" "}
                <select value={draftTier} onChange={(e) => setDraftTier(e.target.value as "user" | "org")}>
                  <option value="user">Your skills</option>
                  <option value="org">Organization</option>
                </select>
              </label>
              <div className="da-skills-actions">
                <button className="da-skillbtn" onClick={() => setFormOpen(false)}>Cancel</button>
                <button className="da-skillbtn is-primary" onClick={() => void submitInstall()}>
                  Install skill
                </button>
              </div>
            </div>
          </div>
        )}

        {TIERS.map(({ tier, label, empty }) => {
          const items = skills.filter((s) => s.tier === tier);
          return (
            <section key={tier} className="da-skills-group">
              <h3>{label}</h3>
              {items.length === 0 ? (
                <p className="da-skills-empty">{empty}</p>
              ) : (
                items.map((s) => <SkillCard key={s.skill_id} skill={s} onChanged={refresh} />)
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
