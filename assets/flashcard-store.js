const PREFIX = 'dokkai:flashcard:1:';
const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;
const STANDARD_EASE = 2.5;

function normalized(text) {
  return text.trim().normalize('NFKC').replace(/\s+/g, ' ');
}

export function cardId(term, reading) {
  return JSON.stringify([normalized(term), normalized(reading)]);
}

export function readCard(id) {
  const value = localStorage.getItem(PREFIX + id);
  return value === null ? null : JSON.parse(value);
}

export function allCards() {
  const cards = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key?.startsWith(PREFIX)) continue;
    let card;
    try {
      card = JSON.parse(localStorage.getItem(key));
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
    if (card?.id && card.term && Number.isFinite(card.due)) cards.push(card);
  }
  return cards;
}

export function addCard(fields, now = Date.now()) {
  const id = cardId(fields.term, fields.reading);
  const existing = readCard(id);
  if (existing) return existing;

  const card = {
    ...fields, id, state: 'new', step: 0, interval: 0,
    ease: STANDARD_EASE, due: now, updatedAt: now,
  };
  localStorage.setItem(PREFIX + id, JSON.stringify(card));
  return card;
}

function learningPlan(card, grade) {
  const relearning = card.state === 'relearning';
  const interval = relearning ? card.interval : 1;
  if (grade === 'easy') return { state: 'review', interval: relearning ? interval + 1 : 4 };
  if (grade === 'good' && (relearning || card.step === 1)) return { state: 'review', interval };
  if (relearning) return { state: 'relearning', step: 0, minutes: grade === 'hard' ? 15 : 10 };
  if (grade === 'again') return { state: 'learning', step: 0, minutes: 1 };
  if (grade === 'hard') return { state: 'learning', step: card.step, minutes: card.step === 0 ? 6 : 10 };
  return { state: 'learning', step: 1, minutes: 10 };
}

function reviewPlan(card, grade) {
  if (grade === 'again') {
    return {
      state: 'relearning', step: 0, minutes: 10,
      interval: Math.max(1, Math.round(card.interval * 0.3)),
      ease: Math.max(1.3, card.ease - 0.2),
    };
  }
  const hard = Math.max(card.interval + 1, Math.round(card.interval * 1.2));
  const good = Math.max(hard + 1, Math.round(card.interval * card.ease));
  const rating = {
    hard: { interval: hard, ease: Math.max(1.3, card.ease - 0.15) },
    good: { interval: good, ease: card.ease },
    easy: { interval: Math.max(good + 1, Math.round(card.interval * card.ease * 1.3)), ease: card.ease + 0.15 },
  };
  return { state: 'review', ...rating[grade] };
}

export function planReview(card, grade, now = Date.now()) {
  const { minutes, ...plan } = card.state === 'review' ? reviewPlan(card, grade) : learningPlan(card, grade);
  const delay = minutes ? minutes * MINUTE : plan.interval * DAY;
  return {
    card: { ...card, ...plan, due: now + delay, updatedAt: now },
    intervalLabel: minutes ? `${minutes} phút` : `${plan.interval} ngày`,
  };
}

export function saveReview(card, grade, now = Date.now()) {
  const current = readCard(card.id);
  if (!current || current.updatedAt !== card.updatedAt || current.due > now) return false;
  const result = planReview(current, grade, now);
  localStorage.setItem(PREFIX + card.id, JSON.stringify(result.card));
  return true;
}
