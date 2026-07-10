document.addEventListener("DOMContentLoaded", () => {
    // Current state variables
    let currentPage = 1;
    const limit = 50;
    let syncIntervalId = null;

    let selectedLicenseValue = "";
    let selectedGroupValue = "";
    let selectedEmailFrequencyValue = "sync";

    // Toast element helper
    const toast = document.getElementById("toast");
    const toastMessage = document.getElementById("toast-message");

    function showToast(message, type = "info") {
        toastMessage.textContent = message;
        toast.className = `toast ${type} show`;
        setTimeout(() => {
            toast.classList.remove("show");
        }, 4000);
    }

    // -------------------------------------------------------------
    // Authentication Logic
    // -------------------------------------------------------------
    const loginOverlay = document.getElementById("login-overlay");
    const loginError = document.getElementById("login-error");
    const loginErrorText = document.getElementById("login-error-text");
    const userDisplayName = document.getElementById("user-display-name");

    window.checkAuth = async function() {
        try {
            const res = await fetch("/api/auth/me");
            if (res.ok) {
                const data = await res.json();
                userDisplayName.textContent = data.username;
                loginOverlay.classList.remove("active");
                
                // Load page data depending on active tab
                const activeTab = document.querySelector(".nav-item.active").getAttribute("data-tab");
                if (activeTab === "dashboard") loadDashboardData();
                else if (activeTab === "users") loadUsersData();
                else if (activeTab === "sync") loadSyncSessions();
                else if (activeTab === "settings") loadSettings();
                
                // Initialize filters once authenticated
                loadFilters(selectedLicenseValue, selectedGroupValue);
            } else {
                loginOverlay.classList.add("active");
            }
        } catch (error) {
            loginOverlay.classList.add("active");
        }
    };

    window.handleLocalLogin = async function() {
        const usernameInput = document.getElementById("login-username");
        const passwordInput = document.getElementById("login-password");
        
        const payload = {
            username: usernameInput.value,
            password: passwordInput.value
        };

        try {
            loginError.style.display = "none";
            const res = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (res.ok) {
                showToast("Вход выполнен успешно!", "success");
                usernameInput.value = "";
                passwordInput.value = "";
                checkAuth();
            } else {
                loginErrorText.textContent = data.detail || "Неверный логин или пароль";
                loginError.style.display = "flex";
            }
        } catch (error) {
            loginErrorText.textContent = "Ошибка сетевого соединения с сервером";
            loginError.style.display = "flex";
        }
    };

    window.handleMicrosoftLogin = async function() {
        try {
            loginError.style.display = "none";
            const res = await fetch("/api/auth/microsoft");
            const data = await res.json();
            
            if (res.ok && data.url) {
                // Redirect user to Microsoft authorization page
                window.location.href = data.url;
            } else {
                loginErrorText.textContent = data.detail || "Не удалось настроить вход M365 (проверьте параметры интеграции)";
                loginError.style.display = "flex";
            }
        } catch (error) {
            loginErrorText.textContent = "Ошибка запуска SSO: " + error.message;
            loginError.style.display = "flex";
        }
    };

    window.handleLogout = async function() {
        try {
            const res = await fetch("/api/auth/logout", { method: "POST" });
            if (res.ok) {
                showToast("Вы вышли из системы.", "info");
                userDisplayName.textContent = "Cloud Management";
                loginOverlay.classList.add("active");
            }
        } catch (error) {
            showToast("Ошибка при выходе из системы", "error");
        }
    };

    window.handleChangePassword = async function() {
        const currentPasswordInput = document.getElementById("current_password");
        const newPasswordInput = document.getElementById("new_password");
        const confirmPasswordInput = document.getElementById("confirm_password");
        
        const oldPwd = currentPasswordInput.value;
        const newPwd = newPasswordInput.value;
        const confPwd = confirmPasswordInput.value;
        
        if (newPwd !== confPwd) {
            showToast("Новые пароли не совпадают!", "error");
            return;
        }
        
        try {
            const res = await fetch("/api/auth/change-password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ current_password: oldPwd, new_password: newPwd })
            });
            const data = await res.json();
            
            if (res.ok) {
                showToast("Пароль успешно изменен!", "success");
                currentPasswordInput.value = "";
                newPasswordInput.value = "";
                confirmPasswordInput.value = "";
            } else {
                showToast(data.detail || "Не удалось изменить пароль.", "error");
            }
        } catch (error) {
            showToast("Ошибка при смене пароля: " + error.message, "error");
        }
    };

    // -------------------------------------------------------------
    // Tab Navigation Logic
    // -------------------------------------------------------------
    const navItems = document.querySelectorAll(".nav-item");
    const tabContents = document.querySelectorAll(".tab-content");
    const pageTitle = document.getElementById("page-title");
    const pageSubtitle = document.getElementById("page-subtitle");

    const tabHeaders = {
        dashboard: { title: "Сводная информация", subtitle: "Статистика и отслеживание изменений лицензий Microsoft 365" },
        users: { title: "Список сотрудников", subtitle: "Таблица пользователей, их назначенных лицензий и групп" },
        sync: { title: "Синхронизация данных", subtitle: "Управление фоновым получением данных и историей сессий" },
        settings: { title: "Настройки системы", subtitle: "Параметры аутентификации M365, отправки почты и планировщика" }
    };

    navItems.forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const targetTab = item.getAttribute("data-tab");
            
            navItems.forEach(nav => nav.classList.remove("active"));
            tabContents.forEach(content => content.classList.remove("active"));

            item.classList.add("active");
            document.getElementById(`tab-${targetTab}`).classList.add("active");

            // Update title and subtitles
            if (tabHeaders[targetTab]) {
                pageTitle.textContent = tabHeaders[targetTab].title;
                pageSubtitle.textContent = tabHeaders[targetTab].subtitle;
            }

            // Load data specific to tabs (only if authenticated)
            if (!loginOverlay.classList.contains("active")) {
                if (targetTab === "dashboard") {
                    loadDashboardData();
                } else if (targetTab === "users") {
                    currentPage = 1;
                    loadUsersData();
                } else if (targetTab === "sync") {
                    loadSyncSessions();
                } else if (targetTab === "settings") {
                    loadSettings();
                }
            }
        });
    });

    // Toggle Settings Visibility based on Options
    const sendViaGraphCheckbox = document.getElementById("send_via_graph");
    const graphMailFields = document.getElementById("graph-mail-fields");
    const smtpMailFields = document.getElementById("smtp-mail-fields");
    
    sendViaGraphCheckbox.addEventListener("change", () => {
        if (sendViaGraphCheckbox.checked) {
            graphMailFields.style.display = "block";
            smtpMailFields.style.display = "none";
        } else {
            graphMailFields.style.display = "none";
            smtpMailFields.style.display = "block";
        }
    });

    const useSmtpAuthCheckbox = document.getElementById("use_smtp_auth");
    const smtpAuthFields = document.getElementById("smtp-auth-fields");

    useSmtpAuthCheckbox.addEventListener("change", () => {
        smtpAuthFields.style.display = useSmtpAuthCheckbox.checked ? "grid" : "none";
    });

    const autoSyncCheckbox = document.getElementById("auto_sync_enabled");
    const syncIntervalContainer = document.getElementById("sync-interval-container");

    autoSyncCheckbox.addEventListener("change", () => {
        syncIntervalContainer.style.display = autoSyncCheckbox.checked ? "grid" : "none";
    });

    // -------------------------------------------------------------
    // Custom Dropdown (Select) UI Handler
    // -------------------------------------------------------------
    document.querySelectorAll(".custom-select .select-trigger").forEach(trigger => {
        trigger.addEventListener("click", (e) => {
            e.stopPropagation();
            const select = trigger.parentElement;
            const isOpen = select.classList.contains("open");
            
            // Close all custom selects first
            document.querySelectorAll(".custom-select").forEach(s => s.classList.remove("open"));
            
            if (!isOpen) {
                select.classList.add("open");
            }
        });
    });

    document.addEventListener("click", () => {
        document.querySelectorAll(".custom-select").forEach(s => s.classList.remove("open"));
    });

    // -------------------------------------------------------------
    // Tab Loaders and Logic
    // -------------------------------------------------------------
    
    // 1. Dashboard Tab
    async function loadDashboardData() {
        try {
            const res = await fetch("/api/dashboard");
            if (!res.ok) {
                if (res.status === 401) { checkAuth(); return; }
                throw new Error("Не удалось загрузить данные дашборда.");
            }
            const data = await res.json();

            // Set simple stats
            document.getElementById("stat-total-users").textContent = data.total_users || 0;
            
            const activeLicCount = Object.keys(data.active_licenses || {}).length;
            document.getElementById("stat-total-licenses").textContent = activeLicCount;
            
            const statusEl = document.getElementById("stat-last-status");
            statusEl.textContent = data.last_sync_status || "Неизвестно";
            statusEl.className = "stat-value " + 
                (data.last_sync_status === "Успешно" ? "text-success" : 
                 data.last_sync_status === "Ошибка" ? "text-danger" : "text-muted");
            
            const indicatorEl = document.querySelector(".sync-status-indicator");
            const dotEl = indicatorEl.querySelector(".status-dot");
            const textEl = document.getElementById("sync-status-text");

            if (data.last_sync_status === "Успешно") {
                dotEl.className = "status-dot green";
                textEl.textContent = "Система готова";
            } else if (data.last_sync_status === "Ошибка") {
                dotEl.className = "status-dot red";
                textEl.textContent = "Ошибка синхронизации";
            }

            const timeEl = document.getElementById("stat-last-time");
            if (data.last_sync_time) {
                const date = new Date(data.last_sync_time);
                timeEl.textContent = date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
            } else {
                timeEl.textContent = "Никогда";
            }

            // Render License Distribution
            const licListEl = document.getElementById("dashboard-licenses-list");
            licListEl.innerHTML = "";
            if (data.active_licenses && Object.keys(data.active_licenses).length > 0) {
                Object.entries(data.active_licenses).forEach(([name, count]) => {
                    const item = document.createElement("div");
                    item.className = "license-item";
                    item.innerHTML = `
                        <span class="license-name">${name}</span>
                        <span class="license-badge">${count}</span>
                    `;
                    licListEl.appendChild(item);
                });
            } else {
                licListEl.innerHTML = '<p class="empty-state">Нет данных о лицензиях.</p>';
            }

            // Render Timeline diffs
            const timelineEl = document.getElementById("dashboard-timeline");
            timelineEl.innerHTML = "";
            if (data.recent_diffs && data.recent_diffs.length > 0) {
                data.recent_diffs.forEach(d => {
                    const item = document.createElement("div");
                    item.className = "timeline-item";
                    
                    const date = new Date(d.timestamp);
                    const dateStr = date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
                    
                    item.innerHTML = `
                        <div class="timeline-dot ${d.change_type}"></div>
                        <div class="timeline-time">${dateStr}</div>
                        <div class="timeline-user">${d.display_name} (${d.user_principal_name})</div>
                        <div class="timeline-desc">${d.details}</div>
                    `;
                    timelineEl.appendChild(item);
                });
            } else {
                timelineEl.innerHTML = '<p class="empty-state">Изменений пока не обнаружено.</p>';
            }
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    // 2. Users Tab
    const userSearch = document.getElementById("user-search");
    const usersTableBody = document.getElementById("users-table-body");
    const prevPageBtn = document.getElementById("prev-page");
    const nextPageBtn = document.getElementById("next-page");
    const pageInfo = document.getElementById("page-info");
    const resetFiltersBtn = document.getElementById("reset-filters-btn");
    const exportExcelBtn = document.getElementById("export-excel-btn");

    async function loadFilters(selectedLicense = "", selectedGroup = "") {
        try {
            const res = await fetch("/api/dashboard");
            if (!res.ok) return;
            const data = await res.json();
            
            // Populate licenses options list
            const licenseOptions = document.getElementById("select-license-options");
            licenseOptions.innerHTML = '<div class="option" data-value="">Все лицензии</div>';
            if (data.active_licenses) {
                Object.keys(data.active_licenses).sort().forEach(lic => {
                    const opt = document.createElement("div");
                    opt.className = "option";
                    opt.dataset.value = lic;
                    opt.textContent = lic;
                    if (lic === selectedLicense) opt.classList.add("active");
                    licenseOptions.appendChild(opt);
                });
            }

            // Populate groups options list
            const usersRes = await fetch("/api/users?limit=1000");
            const groupOptions = document.getElementById("select-group-options");
            groupOptions.innerHTML = '<div class="option" data-value="">Все группы</div>';
            if (usersRes.ok) {
                const usersData = await usersRes.json();
                const uniqueGroups = new Set();
                usersData.users.forEach(u => {
                    if (u.groups) {
                        u.groups.split(",").forEach(g => {
                            const trimmed = g.trim();
                            if (trimmed) uniqueGroups.add(trimmed);
                        });
                    }
                });
                Array.from(uniqueGroups).sort().forEach(grp => {
                    const opt = document.createElement("div");
                    opt.className = "option";
                    opt.dataset.value = grp;
                    opt.textContent = grp;
                    if (grp === selectedGroup) opt.classList.add("active");
                    groupOptions.appendChild(opt);
                });
            }

            // Bind click handlers to newly created option elements
            registerOptionClickListeners("select-license", (val, text) => {
                selectedLicenseValue = val;
                currentPage = 1;
                loadUsersData();
            });
            registerOptionClickListeners("select-group", (val, text) => {
                selectedGroupValue = val;
                currentPage = 1;
                loadUsersData();
            });

        } catch (e) {
            console.error("Error loading filters", e);
        }
    }

    function registerOptionClickListeners(selectContainerId, onSelectCallback) {
        const container = document.getElementById(selectContainerId);
        const triggerSpan = container.querySelector(".select-trigger span");
        const options = container.querySelectorAll(".select-options .option");
        
        options.forEach(opt => {
            const newOpt = opt.cloneNode(true);
            opt.parentNode.replaceChild(newOpt, opt);
            
            newOpt.addEventListener("click", (e) => {
                e.stopPropagation();
                const val = newOpt.dataset.value;
                const text = newOpt.textContent;
                
                triggerSpan.textContent = text;
                
                container.querySelectorAll(".select-options .option").forEach(o => o.classList.remove("active"));
                newOpt.classList.add("active");
                container.classList.remove("open");
                
                onSelectCallback(val, text);
            });
        });
    }

    async function loadUsersData() {
        const search = userSearch.value;
        const lic = selectedLicenseValue;
        const grp = selectedGroupValue;

        // Build query params
        let url = `/api/users?page=${currentPage}&limit=${limit}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        if (lic) url += `&license=${encodeURIComponent(lic)}`;
        if (grp) url += `&group=${encodeURIComponent(grp)}`;

        exportExcelBtn.href = `/api/export`;

        try {
            usersTableBody.innerHTML = '<tr><td colspan="6" class="text-center">Загрузка данных...</td></tr>';
            
            const res = await fetch(url);
            if (!res.ok) {
                if (res.status === 401) { checkAuth(); return; }
                throw new Error("Не удалось загрузить список пользователей.");
            }
            const data = await res.json();

            usersTableBody.innerHTML = "";
            if (data.users && data.users.length > 0) {
                data.users.forEach(u => {
                    const tr = document.createElement("tr");
                    
                    const statusDot = u.account_enabled 
                        ? '<span class="status-dot green" title="Активен"></span>' 
                        : '<span class="status-dot red" title="Отключен"></span>';
                    
                    tr.innerHTML = `
                        <td><strong>${u.display_name}</strong></td>
                        <td>${u.user_principal_name}</td>
                        <td>${u.mail || '<span class="text-muted">—</span>'}</td>
                        <td class="text-center">${statusDot}</td>
                        <td title="${u.licenses}">${u.licenses || '<span class="text-muted">—</span>'}</td>
                        <td title="${u.groups}">${u.groups || '<span class="text-muted">—</span>'}</td>
                    `;
                    usersTableBody.appendChild(tr);
                });

                const totalPages = Math.ceil(data.total / limit) || 1;
                pageInfo.textContent = `Страница ${currentPage} из ${totalPages} (Всего: ${data.total})`;
                
                prevPageBtn.disabled = currentPage <= 1;
                nextPageBtn.disabled = currentPage >= totalPages;
            } else {
                usersTableBody.innerHTML = '<tr><td colspan="6" class="empty-state">Пользователи не найдены. Выполните синхронизацию или измените фильтры.</td></tr>';
                pageInfo.textContent = `Страница 1 из 1`;
                prevPageBtn.disabled = true;
                nextPageBtn.disabled = true;
            }
        } catch (error) {
            usersTableBody.innerHTML = `<tr><td colspan="6" class="text-danger text-center">Ошибка: ${error.message}</td></tr>`;
        }
    }

    // Pagination events
    prevPageBtn.addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            loadUsersData();
        }
    });

    nextPageBtn.addEventListener("click", () => {
        currentPage++;
        loadUsersData();
    });

    // Filtering events
    let searchTimeout;
    userSearch.addEventListener("input", () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentPage = 1;
            loadUsersData();
        }, 400); // 400ms debounce
    });
    
    userSearch.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            clearTimeout(searchTimeout);
            currentPage = 1;
            loadUsersData();
        }
    });

    resetFiltersBtn.addEventListener("click", () => {
        userSearch.value = "";
        selectedLicenseValue = "";
        selectedGroupValue = "";
        
        document.getElementById("select-license-text").textContent = "Все лицензии";
        document.getElementById("select-group-text").textContent = "Все группы";
        
        // Reset active flags inside dropdown lists
        document.querySelectorAll(".custom-select").forEach(select => {
            select.querySelectorAll(".select-options .option").forEach((opt, idx) => {
                if (idx === 0) opt.classList.add("active");
                else opt.classList.remove("active");
            });
        });

        currentPage = 1;
        loadUsersData();
    });

    // 3. Sync Tab
    const syncsTableBody = document.getElementById("syncs-table-body");
    const triggerSyncBtn = document.getElementById("trigger-sync-btn");
    const quickSyncBtn = document.getElementById("quick-sync-btn");
    
    // Sync Progress elements
    const syncProgressBanner = document.getElementById("sync-progress-banner");
    const syncProgressMessage = document.getElementById("sync-progress-message");
    const syncProgressBarFill = document.getElementById("sync-progress-bar-fill");
    const cancelSyncBtn = document.getElementById("cancel-sync-btn");

    async function loadSyncSessions() {
        try {
            const res = await fetch("/api/syncs");
            if (!res.ok) {
                if (res.status === 401) { checkAuth(); return; }
                throw new Error("Не удалось загрузить сессии синхронизации.");
            }
            const data = await res.json();

            syncsTableBody.innerHTML = "";
            if (data && data.length > 0) {
                data.forEach(s => {
                    const tr = document.createElement("tr");
                    
                    const date = new Date(s.timestamp);
                    const dateStr = date.toLocaleString("ru-RU");
                    
                    let statusBadge = "";
                    if (s.status === "success") {
                        statusBadge = '<span class="text-success"><i class="fa-solid fa-circle-check"></i> Успешно</span>';
                    } else if (s.status === "failed") {
                        statusBadge = '<span class="text-danger"><i class="fa-solid fa-circle-xmark"></i> Ошибка</span>';
                    } else if (s.status === "running") {
                        statusBadge = '<span class="text-warning"><i class="fa-solid fa-spinner fa-spin"></i> Выполняется...</span>';
                    }

                    tr.innerHTML = `
                        <td>${dateStr}</td>
                        <td>${statusBadge}</td>
                        <td>${s.users_count}</td>
                        <td title="${s.message}">${s.message || '—'}</td>
                    `;
                    syncsTableBody.appendChild(tr);
                });
            } else {
                syncsTableBody.innerHTML = '<tr><td colspan="4" class="empty-state">Сессии отсутствуют.</td></tr>';
            }
        } catch (error) {
            syncsTableBody.innerHTML = `<tr><td colspan="4" class="text-danger text-center">Ошибка: ${error.message}</td></tr>`;
        }
    }

    async function checkRunningSync() {
        try {
            const checkRes = await fetch("/api/syncs");
            if (checkRes.ok) {
                const syncs = await checkRes.json();
                const latest = syncs[0];
                if (latest && latest.status === "running") {
                    syncProgressBanner.classList.add("active");
                    syncProgressMessage.textContent = latest.message || "Выполняется синхронизация с M365...";
                    syncProgressBarFill.style.width = `${latest.progress || 0}%`;
                    
                    triggerSyncBtn.disabled = true;
                    quickSyncBtn.disabled = true;
                    
                    if (!syncIntervalId) {
                        startStatusPolling();
                    }
                } else {
                    syncProgressBanner.classList.remove("active");
                    triggerSyncBtn.disabled = false;
                    quickSyncBtn.disabled = false;
                    if (syncIntervalId) {
                        clearInterval(syncIntervalId);
                        syncIntervalId = null;
                    }
                }
            }
        } catch (error) {
            console.error("Error checking sync status:", error);
        }
    }

    function startStatusPolling() {
        if (syncIntervalId) clearInterval(syncIntervalId);
        syncIntervalId = setInterval(async () => {
            const activeTab = document.querySelector(".nav-item.active").getAttribute("data-tab");
            
            const checkRes = await fetch("/api/syncs");
            if (checkRes.ok) {
                const syncs = await checkRes.json();
                const latest = syncs[0];
                
                if (latest && latest.status === "running") {
                    syncProgressBanner.classList.add("active");
                    syncProgressMessage.textContent = latest.message || "Выполняется синхронизация с M365...";
                    syncProgressBarFill.style.width = `${latest.progress || 0}%`;
                    triggerSyncBtn.disabled = true;
                    quickSyncBtn.disabled = true;
                } else {
                    clearInterval(syncIntervalId);
                    syncIntervalId = null;
                    syncProgressBanner.classList.remove("active");
                    triggerSyncBtn.disabled = false;
                    quickSyncBtn.disabled = false;
                    
                    const isSuccess = latest.status === "success";
                    showToast(isSuccess ? "Синхронизация завершена успешно!" : "Синхронизация завершена: " + latest.message, isSuccess ? "success" : "error");
                    
                    await loadFilters(selectedLicenseValue, selectedGroupValue);
                    if (activeTab === "dashboard") loadDashboardData();
                    if (activeTab === "users") loadUsersData();
                    if (activeTab === "sync") loadSyncSessions();
                }
            }
            
            if (activeTab === "sync") {
                loadSyncSessions();
            }
        }, 3000);
    }

    async function startSync() {
        try {
            triggerSyncBtn.disabled = true;
            quickSyncBtn.disabled = true;
            
            const res = await fetch("/api/sync", { method: "POST" });
            const data = await res.json();
            
            if (!res.ok) throw new Error(data.detail || "Не удалось запустить синхронизацию.");

            showToast(data.message, "success");
            
            syncProgressBanner.classList.add("active");
            syncProgressMessage.textContent = "Инициализация синхронизации...";
            syncProgressBarFill.style.width = "5%";
            
            startStatusPolling();
        } catch (error) {
            showToast(error.message, "error");
            triggerSyncBtn.disabled = false;
            quickSyncBtn.disabled = false;
        }
    }

    async function cancelSync() {
        try {
            cancelSyncBtn.disabled = true;
            const res = await fetch("/api/sync/cancel", { method: "POST" });
            const data = await res.json();
            
            if (res.ok) {
                showToast(data.message, "info");
                await checkRunningSync();
            } else {
                showToast(data.detail || "Не удалось отменить синхронизацию.", "error");
            }
        } catch (error) {
            showToast("Ошибка при отправке запроса отмены", "error");
        } finally {
            cancelSyncBtn.disabled = false;
        }
    }

    triggerSyncBtn.addEventListener("click", startSync);
    quickSyncBtn.addEventListener("click", startSync);
    cancelSyncBtn.addEventListener("click", cancelSync);

    // 4. Settings Tab
    const settingsForm = document.getElementById("settings-form");

    async function loadSettings() {
        try {
            const res = await fetch("/api/config");
            if (!res.ok) {
                if (res.status === 401) { checkAuth(); return; }
                throw new Error("Не удалось загрузить конфигурацию.");
            }
            const data = await res.json();

            if (data) {
                document.getElementById("tenant_id").value = data.tenant_id || "";
                document.getElementById("client_id").value = data.client_id || "";
                document.getElementById("client_secret").value = data.client_secret || "";
                document.getElementById("email_to").value = data.email_to || "";
                
                const freqVal = data.email_report_frequency || "sync";
                selectedEmailFrequencyValue = freqVal;
                const freqContainer = document.getElementById("select-email-frequency");
                const activeOption = freqContainer.querySelector(`.option[data-value="${freqVal}"]`);
                const triggerText = document.getElementById("select-email-frequency-text");
                if (activeOption) {
                    freqContainer.querySelectorAll(".option").forEach(o => o.classList.remove("active"));
                    activeOption.classList.add("active");
                    triggerText.textContent = activeOption.textContent;
                }
                
                sendViaGraphCheckbox.checked = data.send_via_graph || false;
                sendViaGraphCheckbox.dispatchEvent(new Event("change"));

                document.getElementById("send_from_graph_user").value = data.send_from_graph_user || "";

                document.getElementById("email_from").value = data.email_from || "";
                document.getElementById("smtp_server").value = data.smtp_server || "";
                document.getElementById("smtp_port").value = data.smtp_port || 587;
                
                useSmtpAuthCheckbox.checked = data.use_smtp_auth || false;
                useSmtpAuthCheckbox.dispatchEvent(new Event("change"));

                document.getElementById("smtp_user").value = data.smtp_user || "";
                document.getElementById("smtp_password").value = data.smtp_password || "";

                autoSyncCheckbox.checked = data.auto_sync_enabled || false;
                autoSyncCheckbox.dispatchEvent(new Event("change"));

                document.getElementById("sync_interval_hours").value = data.sync_interval_hours || 24;
            }
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    settingsForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const payload = {
            tenant_id: document.getElementById("tenant_id").value,
            client_id: document.getElementById("client_id").value,
            client_secret: document.getElementById("client_secret").value,
            email_to: document.getElementById("email_to").value,
            email_report_frequency: selectedEmailFrequencyValue,
            send_via_graph: sendViaGraphCheckbox.checked,
            send_from_graph_user: document.getElementById("send_from_graph_user").value,
            email_from: document.getElementById("email_from").value,
            smtp_server: document.getElementById("smtp_server").value,
            smtp_port: parseInt(document.getElementById("smtp_port").value, 10),
            use_smtp_auth: useSmtpAuthCheckbox.checked,
            smtp_user: document.getElementById("smtp_user").value,
            smtp_password: document.getElementById("smtp_password").value,
            auto_sync_enabled: autoSyncCheckbox.checked,
            sync_interval_hours: parseInt(document.getElementById("sync_interval_hours").value, 10)
        };

        try {
            const res = await fetch("/api/config", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (!res.ok) throw new Error(data.detail || "Не удалось сохранить настройки.");
            showToast(data.message, "success");
        } catch (error) {
            showToast(error.message, "error");
        }
    });

    // -------------------------------------------------------------
    // Initial App Load
    // -------------------------------------------------------------
    registerOptionClickListeners("select-email-frequency", (val, text) => {
        selectedEmailFrequencyValue = val;
    });

    // Check if sync is already running on page load
    checkRunningSync();

    checkAuth();
});
