#!/usr/bin/env python3
"""
Split timeline entries that contain both events and appointments into
separate rows, so they can be filtered independently on the timeline.

How it works
------------
1. Each entry's `events` text is split on Chinese sentence-ending periods (。).
2. Each sentence is classified as "appointment" or "event" using regex patterns
   that detect appointment vocabulary (任命, 免去, name任Position, etc.).
3. Entries containing BOTH types are split into two rows:
     - Event row  → keeps original `type` (组织工作)
     - Appt row   → gets `type` = 人事工作, `id` = <original_id>_appt
4. Entries that are purely one type are left unchanged.

Limitations
-----------
- The `translated_text` (English) covers the full original entry; it is kept
  in both output rows unchanged. Splitting English sentences to match the
  Chinese split is non-trivial and left for manual review.
- False positives/negatives are possible — review the output with `--report`
  to spot-check classification decisions.

Usage
-----
  python3 split_timeline_entries.py [INPUT.csv] [OUTPUT.csv] [--report]

Defaults:
  INPUT  = 组织人事工作大事记1978-1997.csv  (same directory as this script)
  OUTPUT = 组织人事工作大事记1978-1997_split.csv

Flags:
  --report   Print a detailed split report instead of writing output.
"""

import csv
import re
import sys
from pathlib import Path

# ── Appointment detection ─────────────────────────────────────────────────────
# Position titles that appear at the END of an appointment target.
# Note: 委员(?!会) avoids false matches on 委员会 (committee).
_POSITIONS = (
    r'总理|副总理|国务委员|部长|副部长|书记|副书记|第一书记'
    r'|主任|副主任|院长|副院长|省长|副省长|市长|副市长'
    r'|局长|副局长|处长|副处长|厅长|副厅长|委员(?!会)|秘书长|副秘书长'
    r'|司令员|政委|参谋长|大使|总领事|行长|副行长|校长|副校长|检察长'
)

APPT_RE = re.compile(
    # Explicit appointment/removal verbs
    r'任命[^，,。]{0,25}为'                           # 任命X为Y
    r'|免去[^，,。]{0,25}职[务]?'                     # 免去X的Y职务
    r'|撤销[^，,。]{0,20}职[务]?'                     # 撤销X职务
    r'|不再[担兼]任'                                  # 不再担任/兼任
    r'|晋升[^，,。]{0,15}(?:' + _POSITIONS + r')'    # 晋升到某职
    r'|调任[^，,。]{0,15}(?:' + _POSITIONS + r')'    # 调任某职
    # Pattern: {2–4 non-punct chars}任{...}{position}  e.g. 齐怀远任外交部副部长
    r'|[^\s，,。；;]{2,4}任[^\s，,。；;]{0,20}(?:' + _POSITIONS + r')'
    # 任命/批准/同意 followed anywhere by a position title (handles commas between verb and name)
    r'|(?:任命|批准|同意)[^。]{0,35}(?:' + _POSITIONS + r')'
    # Implicit "name为position" (after a prior 任命 clause in the same sentence)
    r'|[^\s，,。；;]{2,4}为[^\s，,。；;]{0,20}(?:' + _POSITIONS + r')'
)


def split_sentences(text: str) -> list[str]:
    """Split on 。 keeping the period attached; drop empty parts."""
    return [s.strip() for s in re.split(r'(?<=。)', text) if s.strip()]


def is_appointment(sentence: str) -> bool:
    return bool(APPT_RE.search(sentence))


def process_row(row: dict) -> list[dict]:
    """
    Return 1 row if no split needed, or 2 rows [event_row, appt_row] if mixed.
    """
    text = row['events'].replace('\n', '')
    sentences = split_sentences(text)

    if len(sentences) <= 1:
        return [row]

    appt_sents = [s for s in sentences if is_appointment(s)]
    event_sents = [s for s in sentences if not is_appointment(s)]

    if not appt_sents or not event_sents:
        return [row]

    event_row = dict(row)
    event_row['events'] = ''.join(event_sents)
    # type stays as original (组织工作)

    appt_row = dict(row)
    appt_row['id'] = str(row['id']) + '_appt'
    appt_row['events'] = ''.join(appt_sents)
    appt_row['type'] = '任免'
    # translated_text: kept as full entry text in both rows (see module docstring)

    return [event_row, appt_row]


def main():
    script_dir = Path(__file__).parent
    default_input  = script_dir / '组织人事工作大事记1978-1997.csv'
    default_output = script_dir / '组织人事工作大事记1978-1997_split.csv'

    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    report_mode = '--report' in flags

    input_file  = Path(args[0]) if len(args) > 0 else default_input
    output_file = Path(args[1]) if len(args) > 1 else default_output

    with input_file.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    output_rows = []
    split_entries = []

    for row in rows:
        result = process_row(row)
        output_rows.extend(result)
        if len(result) > 1:
            split_entries.append((row, result))

    # ── MANUAL CORRECTIONS ───────────────────────────────────────────────────
    # Applied after the automatic pass. Each block describes why the auto
    # classification was wrong for that entry and what the correct output is.
    #
    # Two helpers operate on shared mutable dicts that reference the same row
    # objects as output_rows, so edits propagate automatically:
    #
    #   mark_unsplit(id_)   — restore the original unsplit row, mark the
    #                         companion _appt row for deletion.
    #   override(id_, text) — directly set the events text for a row.

    orig_by_id   = {r['id']: r for r in rows}
    output_by_id = {r['id']: r for r in output_rows}
    ids_to_delete = set()

    def mark_unsplit(id_str):
        appt_id = id_str + '_appt'
        if id_str in output_by_id and appt_id in output_by_id:
            orig = orig_by_id[id_str]
            output_by_id[id_str]['events'] = orig['events'].replace('\n', '')
            output_by_id[id_str]['type']   = orig['type']
            ids_to_delete.add(appt_id)

    def override(id_str, text):
        if id_str in output_by_id:
            output_by_id[id_str]['events'] = text

    # ── ID 31 (1979-02-17) ───────────────────────────────────────────────────
    # The APPT row incorrectly includes the institutional-setup sentence
    # ("会议决定设立法制委员会…批准农林部改为农业部") because "以彭真为主任的法制委员会
    # 名单" triggered the position pattern. But that sentence is about establishing
    # agencies; the actual appointments are in the following sentence
    # ("会议任命王任重副总理…"). Fix: event row gets sentences [0]+[1];
    # appt row gets sentence [2] only.
    override('31',
        '17日——23日 第五届全国人大常委会第六次会议在北京举行。'
        '会议决定设立第五届全国人大常委会法制委员会,并通过以彭真为主任的法制委员会名单;'
        '批准设立国家农业委员会、林业部、农业机械部;批准农林部改为农业部,'
        '将水利电力部分设为电力工业部和水利部。')
    override('31_appt',
        '会议任命王任重副总理兼国家农业委员会主任;罗玉川为林业部部长;'
        '霍士廉为农业部部长,免去杨立功的农林部部长职务;杨立功为农业机械部部长;'
        '刘澜波为电力工业部部长;钱正英为水利部部长,免去其水利电力部部长职务;'
        '王磊为商业部部长,免去姚依林的商业部部长职务;曾生为交通部部长,免去叶飞的交通部部长职务;'
        '郑天翔为第七机械工业部部长,免去宋任穷的第七机械工业部部长职务;'
        '蒋南翔为教育部部长,免去刘西尧的教育部部长职务。')

    # ── ID 87 (1979-06-18) ───────────────────────────────────────────────────
    # A notification about NOT combining 书记 and 革委会主任 roles was classified
    # APPT because those title words appear in its subject line. This is a POLICY
    # document, not an appointment. The EVENT clause ("指出这样做有利于党政工作
    # 分开…") is merely the purpose clause of the same sentence. Unsplit.
    mark_unsplit('87')

    # ── ID 92 (1979-07-07) ───────────────────────────────────────────────────
    # "经中央批准，今后…副部长、副省长以上党员干部逝世后，骨灰盒上可覆盖党旗"
    # is a funeral protocol rule, not a personnel appointment. Classification
    # fired on 副部长/副省长 appearing as rank thresholds, not as appointment
    # targets. Unsplit.
    mark_unsplit('92')

    # ── ID 112 (1979-08-25) ──────────────────────────────────────────────────
    # Three sentences describing Zhang Wentian's memorial service were classified
    # APPT because his past titles (总书记、政治局委员、政治局候补委员) appeared.
    # Those are historical credentials in an obituary header, not a new
    # appointment. The real appointment in this entry is the fourth sentence
    # (李恽和任宁夏回族自治区委会副主任). Move the three memorial sentences to
    # the EVENT row; leave only the appointment sentence in the APPT row.
    override('112',
        '25日 中国共产党的优秀党员、老一辈无产阶级革命家、曾任中共中央总书记、'
        '政治局委员、政治局候补委员的张闻天追悼会在北京隆重举行。'
        '张闻天因受林彪、"四人帮"的迫害,于1976年7月1日在江苏无锡含冤逝世,终年70岁。'
        '追悼会由中共中央副主席陈云主持,中共中央副主席邓小平致悼词。')
    override('112_appt',
        '中共中央同意,李恽和任宁夏回族自治区委会副主任。')

    # ── ID 295 (1981-07-14) ──────────────────────────────────────────────────
    # The original entry contains one real appointment (sentence [0]: 酆炳军 et al.
    # appointed as vice ministers of the Railway Ministry) plus a notification
    # about reinstating former capitalists' official status (sentences [1]–[4]).
    # Sentence [2] ("《通知》指出，'文革'中对原工商业者一律撤销其原任职务") fired on
    # "撤销…职务" but describes a HISTORICAL wrong being corrected, not a current
    # removal action. Fix: event row gets sentences [1]+[2]+[3]+[4] (the full
    # notification); appt row gets sentence [0] only.
    override('295',
        '中共中央统战部,中共中央组织部联合发出《关于原工商业者安排使用中几个问题的通知》。'
        '《通知》指出,"文革"中对原工商业者一律撤销其原任职务,并下放劳动,这是不对的。'
        '"文革"前安排为干部和担任领导职务的,应当承认其干部身份。'
        '对在职的原工商业者,不论"文革"以前是否担任领导职务,'
        '都应当根据中央已有文件的精神,合理安排使用。')
    override('295_appt',
        '14日 中共中央同意,酆炳军、李克非、韩力平、刘平田任铁道部副部长。')

    # ── ID 462 (1983-01-05) ──────────────────────────────────────────────────
    # The APPT sentence: "在机构改革中退出领导岗位，或因机构合并，撤销而不担任原来
    # 职务的，其职务自然免除。" This is a GENERAL POLICY RULE about how positions
    # are vacated during institutional restructuring. "撤销…职务" fired, but no
    # specific person is being removed. Unsplit.
    mark_unsplit('462')

    # ── ID 528 (1983-05-21) ──────────────────────────────────────────────────
    # "《关于新任副部长、副省长以上干部生活待遇的几项暂行规定》" describes welfare
    # benefits for officials at that level. "新任" (newly-appointed) is an
    # adjective modifying the position level in the document title, not a verb
    # appointing anyone. Pattern fired because "于新" (2 chars) precedes 任 in
    # "关于新任副部长", producing a spurious {2-char}任{position} match. Unsplit.
    mark_unsplit('528')

    # ── ID 560 (1983-08-10) ──────────────────────────────────────────────────
    # A policy report on cultivating successors to provincial party secretaries.
    # The APPT sentence describes types of posts that young cadres should fill
    # as policy guidance ("选拔一批…担任党政一把手"). "对现任党委常委和正副省长"
    # triggered the pattern: "于现" (2 chars) precedes 任, then 省长 appears later.
    # This is policy language about categories of positions, not a specific
    # appointment. Unsplit.
    mark_unsplit('560')

    # ── ID 612 (1984-03-20) ──────────────────────────────────────────────────
    # Secretariat meeting discussed staffing the Overseas Chinese Affairs Office
    # but ended by asking the Org Dept to "继续考虑" (continue considering). No
    # appointment was actually made; "担任侨办的书记和主任" is the desired outcome
    # of future deliberation. Fired on 书记/主任. Unsplit.
    mark_unsplit('612')

    # ── ID 684 (1984-11-01) ──────────────────────────────────────────────────
    # Approval of a notification about party membership tenure requirements for
    # county-level party committee members and alternate members. "党委委员、候补
    # 委员" triggered the pattern, but this is procedural policy about membership
    # requirements, not appointments. Unsplit.
    mark_unsplit('684')

    # ── ID 714 (1985-02-01) ──────────────────────────────────────────────────
    # Provisional regulations specifying delegate quotas and committee member
    # counts (委员, 候补委员, 主任, 书记, etc.) for party congresses. Position
    # titles appear throughout as structural categories, not appointment targets.
    # Unsplit.
    mark_unsplit('714')

    # ── ID 943 (1986-12-08) ──────────────────────────────────────────────────
    # "《意见》规定，县级人大常委会主任、副主任以及委员应能任满一届" sets term-
    # completion requirements for NPC standing committee positions. Fired on
    # 主任/副主任/委员 as position titles in a policy rule, not as appointment
    # targets. Unsplit.
    mark_unsplit('943')

    # ── ID 1183 (1988-11-17) ─────────────────────────────────────────────────
    # News report about a training class for 中直机关党委书记 (party committee
    # secretaries of central directly-subordinate organs). Fired on 书记 in the
    # class title and 副书记 in the participant description. This is an educational
    # program announcement, not an appointment. Unsplit.
    mark_unsplit('1183')

    # ── ID 1385 (1989-12-27) ─────────────────────────────────────────────────
    # Central notification establishing a mandatory study system for provincial
    # and ministerial-level leaders. Every sentence is about study and training
    # requirements. "不担任领导职务的中央委员、候补中央委员" (non-leadership Central
    # Committee members) triggered the pattern; 委员 here identifies a category
    # of people subject to training rules, not appointment targets. Unsplit.
    mark_unsplit('1385')

    # ── ID 1446 (1990-04-14) ─────────────────────────────────────────────────
    # News report on 1989 party discipline statistics. "党员受撤职以上三种处分的
    # 人数共75719人，其中…撤销党内职务的4498人" reports aggregate numbers of
    # disciplinary actions across all categories. "撤销…职务" fired, but this is
    # statistical reporting, not a specific personnel action against a named
    # individual. Unsplit.
    mark_unsplit('1446')

    # ── ID 1472 (1990-06-07) ─────────────────────────────────────────────────
    # A party discipline notification about expelling 罗云光 (铁道部原副部长) and
    # others for bribery. "原副部长" identifies the person's former position as
    # context; it is not an appointment action. Fired on 副部长 in the name/title
    # phrase "铁道部原副部长罗云光". Unsplit.
    mark_unsplit('1472')

    # ── ID 1594 (1991-03-11) ─────────────────────────────────────────────────
    # News report on the corruption case of 武振国, former Luoyang party secretary.
    # "于1985年至1988年担任洛阳市委书记、市长期间" describes the past offices during
    # which he committed crimes; 书记/市长 here are historical identifiers, not
    # appointment targets. Unsplit.
    mark_unsplit('1594')

    # ── ID 1688 (1991-09-24) ─────────────────────────────────────────────────
    # Circular about misconduct during the Luoyang NPC election. "受到降职处分的
    # 原市长韩西英同志为自己争当市长" describes an improper self-promotion attempt;
    # 市长 triggered the pattern but this is a discipline notification, not an
    # appointment. Unsplit.
    mark_unsplit('1688')

    # ── ID 1729 (1992-01-16) ─────────────────────────────────────────────────
    # Notification specifying age limits (任职年龄界限) for officials in provincial
    # people's congresses and consultative conferences. "担任主任、主席职务的…任职
    # 年龄界限仍为70岁" describes age-limit policy for role categories. Fired on
    # 主任/主席 as position titles in a policy rule. Unsplit.
    mark_unsplit('1729')

    # ── ID 1790 (1992-07-01) ─────────────────────────────────────────────────
    # National conference on party building in universities. 李铁映 is introduced
    # as "中共中央政治局委员、国务委员兼国家教育委员会主任、党组书记" — a description
    # of his credentials as the keynote speaker. This is not an appointment.
    # Fired on 主任/书记. Unsplit.
    mark_unsplit('1790')

    # ── ID 2052 (1993-07-21) ─────────────────────────────────────────────────
    # National institutional reform conference. 胡锦涛 is identified as "政治局
    # 常委、书记处书记、中央机构编制委员会副主任" as the meeting's presiding officer.
    # This is a credential description, not an appointment. Fired on 副主任.
    # Unsplit.
    mark_unsplit('2052')

    # ── ID 2131 (1993-12-13) ─────────────────────────────────────────────────
    # Anti-corruption conference. 曾庆红 is introduced as "中共中央办公厅主任、
    # 中央直属机关工作委员会书记" as the speaker. Description of credentials, not
    # an appointment. Fired on 主任/书记. Unsplit.
    mark_unsplit('2131')

    # ── ID 2481 (1996-06-12) ─────────────────────────────────────────────────
    # Notification about a training program; its eligibility list enumerates
    # nearly every position title (省委书记、常委、市长、院长、检察长, etc.) as
    # participant categories. Multiple patterns fired on these title words.
    # Entirely policy/eligibility language, no actual appointments. Unsplit.
    mark_unsplit('2481')

    # ── ID 2791 (1987-10-20) ─────────────────────────────────────────────────
    # Describes the consultation process for draft civil service regulations.
    # The phrase "办公室主任、人事处长" (office directors, personnel division chiefs)
    # lists the types of officials who participated in consultations. Pattern
    # fired because "室主" (2 chars) precedes 任 in 主任, then 处长 follows.
    # This is an event description of a policy drafting process. Unsplit.
    mark_unsplit('2791')

    # ── ID 1712 (1991-11-25) ─────────────────────────────────────────────────
    # A policy document with numbered section headers (二、目标和要求 / 三、主要
    # 任务 / 五、政策和措施 / 六、管理和分工 etc.). These headers each end with 。
    # and so split into isolated one-line EVENT fragments, which are meaningless
    # on their own. The entry should stay together as a single row. Unsplit.
    mark_unsplit('1712')

    # ── Apply deletions ───────────────────────────────────────────────────────
    output_rows = [r for r in output_rows if r['id'] not in ids_to_delete]

    # ── Report / write ────────────────────────────────────────────────────────
    if report_mode:
        print(f"{'='*70}")
        print(f"SPLIT REPORT  —  {len(split_entries)} entries split (before corrections)")
        print(f"{'='*70}\n")
        for orig, (ev, ap) in split_entries[:30]:
            print(f"ID {orig['id']}  ({orig['start_date']})")
            print(f"  EVENT : {ev['events'][:120]}")
            print(f"  APPT  : {ap['events'][:120]}")
            print()
        if len(split_entries) > 30:
            print(f"... and {len(split_entries) - 30} more.")
        return

    with output_file.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    auto_splits   = len(split_entries)
    corrections   = len(ids_to_delete)
    final_splits  = auto_splits - corrections
    print(f"Input  rows      : {len(rows):>5}")
    print(f"Auto splits      : {auto_splits:>5}")
    print(f"Manual unsplits  : {corrections:>5}  (false positives corrected)")
    print(f"Net splits       : {final_splits:>5}")
    print(f"Output rows      : {len(output_rows):>5}")
    print(f"Written to       : {output_file}")


if __name__ == '__main__':
    main()
