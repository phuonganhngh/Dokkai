import { allCards, planReview, saveReview } from './flashcard-store.js';

const byId = (id) => document.getElementById(id);
const study = byId('study-card');
const counts = byId('card-counts');
const back = byId('card-back');
const reveal = byId('show-answer');
const grades = byId('grades');
const gradeButtons = [...grades.querySelectorAll('button')];
const empty = byId('empty-state');
const status = byId('storage-status');
const formatter = new Intl.DateTimeFormat('vi', { dateStyle: 'medium', timeStyle: 'short' });
let active = null;
let nextDueTimer;

function showCard(card, focus) {
  active = card;
  byId('card-word').textContent = card.term;
  byId('card-meaning').textContent = card.meaning;
  const reading = byId('card-reading');
  reading.textContent = card.reading;
  reading.hidden = !card.reading;
  const link = byId('card-source');
  const allowedSource = card.source?.startsWith(`${location.origin}/`);
  link.hidden = !allowedSource;
  if (allowedSource) link.href = card.source;
  back.hidden = true;
  grades.hidden = true;
  reveal.hidden = false;
  if (focus) reveal.focus();
}

function refresh(focus = false) {
  clearTimeout(nextDueTimer);
  let cards;
  try {
    cards = allCards();
  } catch {
    study.hidden = true;
    empty.hidden = true;
    counts.hidden = true;
    status.textContent = 'Trình duyệt chưa cho phép truy cập bộ thẻ.';
    return;
  }
  const now = Date.now();
  const due = cards.filter((card) => card.due <= now);
  due.sort((first, second) => (first.state === 'new') - (second.state === 'new') || first.due - second.due);
  const newCount = due.filter((card) => card.state === 'new').length;
  counts.hidden = false;
  counts.textContent = `${cards.length} thẻ · ${newCount} mới · ${due.length - newCount} đến hạn`;
  study.hidden = due.length === 0;
  empty.hidden = !study.hidden;
  if (due.length) {
    if (!due.some((card) => card.id === active?.id && card.updatedAt === active.updatedAt)) {
      showCard(due[0], focus);
    }
    return;
  }
  active = null;
  byId('empty-title').textContent = cards.length ? 'Đã ôn hết thẻ đến hạn' : 'Chưa có flashcard';
  const next = cards.length ? Math.min(...cards.map((card) => card.due)) : null;
  byId('empty-detail').textContent = next
    ? `Lần ôn tiếp theo vào ${formatter.format(next)}.`
    : 'Trong phần từ vựng của đề, chọn 復 rồi bấm Thêm vào Flashcard.';
  if (next) nextDueTimer = setTimeout(refresh, Math.min(next - now + 50, 2_147_483_647));
  if (focus) byId('open-exams').focus();
}

reveal.addEventListener('click', () => {
  back.hidden = false;
  grades.hidden = false;
  reveal.hidden = true;
  for (const button of gradeButtons) {
    button.querySelector('small').textContent = planReview(active, button.dataset.grade).intervalLabel;
  }
  gradeButtons[0].focus();
});

grades.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-grade]');
  if (!button || !active || grades.hidden) return;
  try {
    const saved = saveReview(active, button.dataset.grade);
    status.textContent = saved ? '' : 'Thẻ vừa được cập nhật ở tab khác.';
    active = null;
    refresh(true);
  } catch {
    status.textContent = 'Không lưu được lịch ôn. Bạn có thể thử lại.';
  }
});

window.addEventListener('storage', () => refresh());
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refresh();
});
refresh();
