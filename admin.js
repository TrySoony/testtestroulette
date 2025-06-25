document.addEventListener('DOMContentLoaded', () => {
    const userList = document.getElementById('user-list');
    const spinner = document.querySelector('.spinner-container');
    const modal = document.getElementById('add-prize-modal');
    const closeModalButton = document.querySelector('.close-button');
    const addPrizeForm = document.getElementById('add-prize-form');
    const modalUserIdInput = document.getElementById('modal-user-id');
    
    let adminId = null;

    function initializeApp() {
        alert('V1.2: Initializing Admin App...');
        try {
            const tg = window.Telegram.WebApp;
            tg.ready();
            tg.expand();

            alert(`V1.2: tg.initDataUnsafe: ${JSON.stringify(tg.initDataUnsafe, null, 2)}`);

            if (tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.id) {
                adminId = tg.initDataUnsafe.user.id;
                fetchData();
            } else {
                let errorDetails = [`tg.initData: ${tg.initData}`, `tg.initDataUnsafe: ${JSON.stringify(tg.initDataUnsafe, null, 2)}`];
                const friendlyMessage = "Это приложение должно запускаться из Telegram.\nПожалуйста, не открывайте ссылку напрямую в браузере. Вернитесь в бот и нажмите кнопку 'Открыть админ-панель'.";
                showError("Ошибка: Не удалось получить ID администратора.\n\n" + friendlyMessage + "\n\n--- Техническая информация ---\n" + errorDetails.join('\n'));
                spinner.style.display = 'none';
            }
        } catch(e) {
            showError(`V1.2 Critical initialization error: ${e.message}. The app must be run from Telegram.`);
            spinner.style.display = 'none';
        }
    }

    initializeApp();
    
    async function fetchData() {
        spinner.style.display = 'flex';
        userList.innerHTML = '';
        try {
            const response = await fetch('/api/admin/user_data');
            const users = await response.json();
            if (Object.keys(users).length === 0) {
                 userList.innerHTML = '<p class="empty-state">Пока что нет данных об игроках.</p>';
            } else {
                renderUsers(users);
            }
        } catch (error) {
            console.error('Ошибка при загрузке данных пользователей:', error);
            showError("Не удалось загрузить данные пользователей.");
        } finally {
            spinner.style.display = 'none';
        }
    }

    function renderUsers(users) {
        userList.innerHTML = '';
        for (const userId in users) {
            const userData = users[userId];
            const userCard = document.createElement('div');
            userCard.className = 'user-card';
            userCard.dataset.userId = userId;

            const giftsHTML = userData.gifts.map((gift, index) => `
                <li class="gift-item">
                    <img src="${gift.img || 'images/default_gift.png'}" class="gift-image" alt="prize">
                    <span>${gift.name} (${gift.starPrice}★) - ${gift.date}</span>
                    <button class="button danger small remove-gift-btn" data-index="${index}">Удалить</button>
                </li>
            `).join('');

            userCard.innerHTML = `
                <div class="user-card-header">
                    <h3>ID: ${userId}</h3>
                    <div class="user-actions">
                         <button class="button primary small add-prize-btn">Выдать приз</button>
                         <button class="button secondary small add-attempt-btn">+1 Попытка</button>
                         <button class="button danger small reset-attempts-btn">Сбросить попытки</button>
                    </div>
                </div>
                <div class="user-card-body">
                    <p>Попыток использовано: <span class="attempts-count">${userData.attempts}</span></p>
                    <p>Доступно попыток: <span class="attempts-left">${2 - userData.attempts}</span></p>
                    <h4>Призы:</h4>
                    <ul class="gift-list">${giftsHTML || '<p>Нет призов</p>'}</ul>
                </div>
            `;
            userList.appendChild(userCard);
        }
    }

    // Обработчики событий
    userList.addEventListener('click', (e) => {
        const userId = e.target.closest('.user-card')?.dataset.userId;
        if (!userId) return;

        if (e.target.classList.contains('add-attempt-btn')) {
            addAttempt(userId);
        }
        if (e.target.classList.contains('reset-attempts-btn')) {
            resetAttempts(userId);
        }
        if (e.target.classList.contains('remove-gift-btn')) {
            const giftIndex = parseInt(e.target.dataset.index, 10);
            removeGift(userId, giftIndex);
        }
        if(e.target.classList.contains('add-prize-btn')) {
            openAddPrizeModal(userId);
        }
    });

    closeModalButton.onclick = () => modal.style.display = "none";
    window.onclick = (event) => {
        if (event.target == modal) {
            modal.style.display = "none";
        }
    }

    addPrizeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const userId = modalUserIdInput.value;
        const prize = {
            name: document.getElementById('prize-name').value,
            starPrice: parseInt(document.getElementById('prize-price').value, 10),
            img: document.getElementById('prize-img').value
        };
        await addPrize(userId, prize);
        modal.style.display = "none";
        addPrizeForm.reset();
    });
    
    function openAddPrizeModal(userId) {
        modalUserIdInput.value = userId;
        modal.style.display = "flex";
    }

    // Функции API
    async function apiCall(endpoint, body) {
        if (!adminId) {
            showError("Действие невозможно: ID администратора не найден.");
            return;
        }
        
        // Дополнительная проверка, что adminId - это число
        const adminIdNum = parseInt(adminId, 10);
        if (isNaN(adminIdNum) || adminIdNum <= 0) {
            showError(`Действие невозможно: некорректный ID администратора (${adminId}).`);
            return;
        }

        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...body, admin_id: adminIdNum })
            });
            if (!response.ok) {
                 const error = await response.json();
                 throw new Error(error.error || 'Ошибка сервера');
            }
            return await response.json();
        } catch (error) {
            console.error(`Ошибка при вызове ${endpoint}:`, error);
            showError(error.message);
            return null; // Возвращаем null при ошибке
        }
    }

    async function addAttempt(userId) {
        const result = await apiCall('/api/admin/add_attempt', { user_id: userId });
        if (result && result.success) {
            // Обновляем UI
            const attemptsSpan = document.querySelector(`.user-card[data-user-id="${userId}"] .attempts-count`);
            const attemptsLeftSpan = document.querySelector(`.user-card[data-user-id="${userId}"] .attempts-left`);
            if (attemptsSpan) attemptsSpan.textContent = result.attempts;
            if (attemptsLeftSpan) attemptsLeftSpan.textContent = 2 - result.attempts;
            showSuccess("Попытка добавлена!");
        }
    }

    async function resetAttempts(userId) {
        if (!confirm('Вы уверены, что хотите сбросить попытки этого пользователя?')) return;
        const result = await apiCall('/api/admin/reset_attempts', { user_id: userId });
        if (result && result.success) {
            // Обновляем UI
            const attemptsSpan = document.querySelector(`.user-card[data-user-id="${userId}"] .attempts-count`);
            const attemptsLeftSpan = document.querySelector(`.user-card[data-user-id="${userId}"] .attempts-left`);
            if (attemptsSpan) attemptsSpan.textContent = '0';
            if (attemptsLeftSpan) attemptsLeftSpan.textContent = '2';
            showSuccess("Попытки сброшены!");
        }
    }

    async function removeGift(userId, giftIndex) {
        if (!confirm('Вы уверены, что хотите удалить этот приз?')) return;
        const result = await apiCall('/api/admin/remove_gift', { user_id: userId, gift_index: giftIndex });
        if (result && result.success) {
            // Просто перезагружаем все данные для простоты
            fetchData();
            showSuccess("Приз удален!");
        }
    }

    async function addPrize(userId, prize) {
        const result = await apiCall('/api/admin/add_prize', { user_id: userId, prize: prize });
        if (result && result.success) {
            fetchData();
            showSuccess("Приз выдан!");
        }
    }
    
    function showError(message) {
        // Можно заменить на красивую нотификацию
        alert(`Ошибка: ${message}`);
    }
    
    function showSuccess(message) {
        // Можно заменить на красивую нотификацию
        alert(`Успех: ${message}`);
    }
}); 