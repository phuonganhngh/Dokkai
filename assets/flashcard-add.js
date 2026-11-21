import { addCard, cardId, readCard } from './flashcard-store.js';

const flashcardPage = new URL('../flashcard.html', import.meta.url);
const text = (parent, selector) => parent.querySelector(selector)?.textContent.trim() || '';

function addControls(vocab, unknown) {
  let controls = vocab.querySelector('.flashcard-add');
  if (!unknown) {
    controls?.remove();
    return;
  }
  const term = text(vocab, '.vocab-term');
  const reading = text(vocab, '.vocab-definition .reading');
  const meaning = text(vocab, '.vocab-definition > p:not(.small)');
  const lesson = vocab.closest('.lesson');
  if (!term || !meaning || !lesson) return;
  const source = new URL(location.pathname, location.origin);
  source.hash = lesson.id;

  if (controls) return;
  controls = document.createElement('div');
  controls.className = 'flashcard-add no-print';
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = 'Thêm vào Flashcard';
  button.setAttribute('aria-label', `Thêm ${term} vào Flashcard`);
  const link = document.createElement('a');
  link.href = flashcardPage;
  link.textContent = 'Đã thêm · Mở Flashcard';
  link.hidden = true;
  const status = document.createElement('span');
  status.setAttribute('role', 'status');

  function showSaved() {
    const moveFocus = document.activeElement === button;
    button.hidden = true;
    link.hidden = false;
    if (moveFocus) link.focus();
  }

  try {
    if (readCard(cardId(term, reading))) showSaved();
  } catch {
    status.textContent = 'Trình duyệt chưa cho phép truy cập bộ thẻ.';
  }

  button.addEventListener('click', () => {
    try {
      addCard({ term, reading, meaning, source: source.href });
      status.textContent = '';
      showSaved();
    } catch {
      status.textContent = 'Không lưu được thẻ. Hãy kiểm tra dung lượng và quyền lưu dữ liệu của trình duyệt.';
    }
  });
  controls.append(button, link, status);
  vocab.querySelector('.vocab-definition').append(controls);
}

document.addEventListener('change', (event) => {
  const choice = event.target;
  if (!choice.matches('.vocab-rating input[type="radio"]')) return;
  addControls(choice.closest('.vocab'), choice.value === 'unknown');
});

window.addEventListener('pageshow', () => {
  for (const choice of document.querySelectorAll('.vocab-rating input[type="radio"]:checked')) {
    addControls(choice.closest('.vocab'), choice.value === 'unknown');
  }
});
