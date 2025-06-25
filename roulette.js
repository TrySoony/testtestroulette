const roulette = document.getElementById('roulette');
const spinBtn = document.getElementById('spin');
const resultDiv = document.getElementById('result');
const giftsList = document.getElementById('gifts-list');

let currentUser = {}; // Храним ID пользователя
let attemptsLeft = 0; // Храним оставшиеся попытки
let userGifts = [];
let telegramUser = null;

function showError(message) {
    alert(message);
}

function initializeApp() {
    try {
        const tg = window.Telegram.WebApp;
        tg.ready();

        if (tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.id) {
            telegramUser = tg.initDataUnsafe.user;
            
            tg.expand();
            if (tg.BackButton.isVisible) {
                tg.BackButton.hide();
            }

            announceUser(telegramUser.id).then(() => {
                fetchUserStatus(telegramUser.id);
            });

        } else {
            let errorDetails = [`tg.initData: ${tg.initData}`, `tg.initDataUnsafe: ${JSON.stringify(tg.initDataUnsafe, null, 2)}`];
            const friendlyMessage = "Это приложение должно запускаться из Telegram.\nПожалуйста, не открывайте ссылку напрямую в браузере. Вернитесь в бот и нажмите кнопку 'Открыть рулетку'.";
            showError("Ошибка: не удалось получить данные пользователя.\n\n" + friendlyMessage + "\n\n--- Техническая информация ---\n" + errorDetails.join('\n'));
            spinBtn.disabled = true;
        }
    } catch (e) {
        showError(`V1.2 Critical initialization error: ${e.message}. The app must be run from Telegram.`);
        spinBtn.disabled = true;
    }
}

// Новая функция для создания/анонсирования пользователя на сервере
async function announceUser(userId) {
  // Валидация userId на клиенте
  if (!userId || typeof userId !== 'number' || userId <= 0) {
    console.error('Invalid user ID:', userId);
    throw new Error('Invalid user ID');
  }

  try {
    const response = await fetch('/api/user', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId })
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || 'Server error');
    }
    
    const data = await response.json();
    console.log('User announced successfully:', data.message);
    currentUser.id = userId; // Устанавливаем ID текущего пользователя
  } catch (error) {
    console.error("Error announcing user:", error);
    throw error;
  }
}

// Получаем статус пользователя с сервера
async function fetchUserStatus(userId) {
  // Валидация userId на клиенте
  if (!userId || typeof userId !== 'number' || userId <= 0) {
    console.error('Invalid user ID:', userId);
    throw new Error('Invalid user ID');
  }

  try {
    const response = await fetch(`/api/get_user_status?user_id=${userId}`);
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || 'Server error');
    }
    
    const data = await response.json();
    attemptsLeft = data.attempts_left;
    updateSpinBtnState();
    updateGiftsList(data.gifts); // Сразу обновляем список подарков
  } catch (error) {
    console.error("Failed to fetch user status:", error);
    throw error;
  }
}

function updateSpinBtnState() {
  spinBtn.disabled = attemptsLeft <= 0;
  if (attemptsLeft <= 0) {
    spinBtn.textContent = 'Попытки закончились';
  } else {
    spinBtn.textContent = `Крутить! (${attemptsLeft} left)`;
  }
}

function renderPrizes(extendedPrizes) {
  roulette.innerHTML = '';
  extendedPrizes.forEach(prize => {
    const div = document.createElement('div');
    div.className = 'prize';
    if (prize.img) {
      div.innerHTML = `<img src="${prize.img}" class="prize-img" alt="${prize.name}">
                       <div class="prize-name">${prize.name}</div>
                       <div class="prize-price">${prize.starPrice}⭐</div>`;
    } else {
      div.innerHTML = `<div class="prize-name" style="font-size:18px;">${prize.name}</div>
                       <div class="prize-price" style="color:#bbb;">Пусто</div>`;
    }
    roulette.appendChild(div);
  });
}

function getPrizeWidth() {
  const tempPrize = document.createElement('div');
  tempPrize.className = 'prize';
  tempPrize.style.visibility = 'hidden';
  tempPrize.textContent = 'test';
  roulette.appendChild(tempPrize);
  const prizeWidth = tempPrize.offsetWidth +
    parseInt(getComputedStyle(tempPrize).marginLeft) +
    parseInt(getComputedStyle(tempPrize).marginRight);
  roulette.removeChild(tempPrize);
  return prizeWidth;
}

// Функция для запуска конфетти-салюта
function launchConfetti() {
  const duration = 3 * 1000;
  const animationEnd = Date.now() + duration;
  const defaults = { startVelocity: 30, spread: 360, ticks: 60, zIndex: 101 };

  function randomInRange(min, max) {
    return Math.random() * (max - min) + min;
  }

  const interval = setInterval(function() {
    const timeLeft = animationEnd - Date.now();
    if (timeLeft <= 0) {
      return clearInterval(interval);
    }
    const particleCount = 50 * (timeLeft / duration);
    // Запускаем конфетти с двух сторон для эффекта салюта
    confetti({ ...defaults, particleCount, origin: { x: randomInRange(0.1, 0.3), y: Math.random() - 0.2 } });
    confetti({ ...defaults, particleCount, origin: { x: randomInRange(0.7, 0.9), y: Math.random() - 0.2 } });
  }, 250);
}

// Управление модальным окном
const winModalOverlay = document.getElementById('win-modal-overlay');
const winModalImg = document.getElementById('win-modal-img');
const winModalTitle = document.getElementById('win-modal-title');
const winModalPrice = document.getElementById('win-modal-price');
const winModalBtn = document.getElementById('win-modal-btn');

function showWinModal(prize) {
  winModalImg.src = prize.img;
  winModalTitle.textContent = prize.name;
  winModalPrice.textContent = `${prize.starPrice}⭐`;
  winModalOverlay.classList.add('visible');
  launchConfetti(); // Запускаем конфетти вместе с окном
}

function hideWinModal() {
  winModalOverlay.classList.remove('visible');
}

// Закрытие модального окна
winModalOverlay.addEventListener('click', (e) => {
  if (e.target === winModalOverlay) {
    hideWinModal();
  }
});
winModalBtn.addEventListener('click', () => {
  hideWinModal();
  // Переключаемся на вкладку "Мои подарки"
  document.querySelector('.tab-btn[data-tab="gifts"]').click();
});

async function spinRoulette() {
  if (attemptsLeft <= 0) {
    showError("У вас не осталось попыток.");
    return;
  }
  spinBtn.disabled = true;

  try {
    // 1. Сначала получаем результат с сервера
    const response = await fetch('/api/spin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: currentUser.id })
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || 'Не удалось выполнить прокрутку');
    }

    const wonPrize = data.won_prize;
    const prizeIndex = prizes.findIndex(p => p.name === wonPrize.name);
    
    if (prizeIndex === -1) {
        throw new Error("Сервер вернул неизвестный приз.");
    }

    // 2. Теперь запускаем анимацию, зная точный результат
    const prizeCount = prizes.length;
    const prizeWidth = getPrizeWidth();
    const visibleCount = Math.floor(roulette.parentElement.offsetWidth / prizeWidth);
    const centerIndex = Math.floor(visibleCount / 2);

    const rounds = 5; // Фиксированное количество оборотов для предсказуемости
    const totalSteps = rounds * prizeCount + prizeIndex;
    const extendedLength = totalSteps + visibleCount + 2;
    let extendedPrizes = [];
    while (extendedPrizes.length < extendedLength) {
        extendedPrizes = extendedPrizes.concat(prizes);
    }
    extendedPrizes = extendedPrizes.slice(0, extendedLength);

    renderPrizes(extendedPrizes);
    
    // Сбрасываем старые анимации
    roulette.style.transition = 'none';
    roulette.style.transform = 'translateX(0)';
    roulette.classList.remove('spinning');

    // Даем браузеру обновиться
    await new Promise(resolve => requestAnimationFrame(resolve));

    const offset = (totalSteps - centerIndex) * prizeWidth;
    
    // Устанавливаем анимацию
    roulette.style.transition = 'transform 5s cubic-bezier(0.2, 0.8, 0.2, 1)';
    roulette.style.transform = `translateX(-${offset}px)`;

    // 3. Обновляем состояние и показываем результат после завершения анимации
    roulette.addEventListener('transitionend', () => {
        attemptsLeft = data.attempts_left;
        updateSpinBtnState();

        if (wonPrize.starPrice > 0) {
            showWinModal(wonPrize);
            fetchUserStatus(currentUser.id); // Обновляем список подарков
        } else {
            resultDiv.textContent = `Вы ничего не выиграли.`;
        }
        spinBtn.disabled = false; // Разблокируем кнопку после завершения
    }, { once: true });


  } catch (error) {
    console.error('Error during spin:', error);
    showError(`Ошибка: ${error.message}`);
    spinBtn.disabled = false; // Разблокируем кнопку в случае ошибки
  }
}

// Первичная отрисовка (по умолчанию 3 круга)
(function(){
  const prizeCount = prizes.length;
  const prizeWidth = getPrizeWidth();
  const visibleCount = Math.floor(roulette.parentElement.offsetWidth / prizeWidth);
  const rounds = 3;
  const totalSteps = rounds * prizeCount;
  const extendedLength = totalSteps + visibleCount + 2;
  let extendedPrizes = [];
  while (extendedPrizes.length < extendedLength) {
    extendedPrizes = extendedPrizes.concat(prizes);
  }
  extendedPrizes = extendedPrizes.slice(0, extendedLength);
  renderPrizes(extendedPrizes);
})();

// При загрузке страницы обновляем состояние кнопки
updateSpinBtnState();

initializeApp();