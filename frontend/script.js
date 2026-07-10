document.addEventListener("DOMContentLoaded", () => {
    // Current state variables
    let currentPage = 1;
    const limit = 50;
    let syncIntervalId = null;

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

    // Tab Navigation Logic
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

            // Load data specific to tabs
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
    // Tab Loaders and Logic
    // -------------------------------------------------------------
    
    // 1. Dashboard Tab
    async function loadDashboardData() {
        try {
            const res = await fetch("/api/dashboard");
            if (!res.ok) throw new Error("Не удалось загрузить данные дашборда.");
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
    const filterLicense = document.getElementById("filter-license");
    const filterGroup = document.getElementById("filter-group");
    const usersTableBody = document.getElementById("users-table-body");
    const prevPageBtn = document.getElementById("prev-page");
    const nextPageBtn = document.getElementById("next-page");
    const pageInfo = document.getElementById("page-info");
    const resetFiltersBtn = document.getElementById("reset-filters-btn");
    const exportExcelBtn = document.getElementById("export-excel-btn");

    async function loadFilters(selectedLicense = "", selectedGroup = "") {
        try {
            // Load filters by getting all users from dashboard or making request
            // In a larger system, we'd have specialized filter endpoints, 
            // but we can query dashboard stats for licenses.
            const res = await fetch("/api/dashboard");
            if (!res.ok) return;
            const data = await res.json();
            
            // Populate licenses dropdown
            filterLicense.innerHTML = '<option value="">Все лицензии</option>';
            if (data.active_licenses) {
                Object.keys(data.active_licenses).sort().forEach(lic => {
                    const opt = document.createElement("option");
                    opt.value = lic;
                    opt.textContent = lic;
                    if (lic === selectedLicense) opt.selected = true;
                    filterLicense.appendChild(opt);
                });
            }

            // Populate groups (we can fetch groups from config or list of users dynamically)
            // For now, let's keep it simple: load from users list or query it.
            // Let's make an API call to get all syncs and fetch group names.
            // Since groups are saved, we can query users with limit 1000 to extract unique groups.
            const usersRes = await fetch("/api/users?limit=1000");
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
                filterGroup.innerHTML = '<option value="">Все группы</option>';
                Array.from(uniqueGroups).sort().forEach(grp => {
                    const opt = document.createElement("option");
                    opt.value = grp;
                    opt.textContent = grp;
                    if (grp === selectedGroup) opt.selected = true;
                    filterGroup.appendChild(opt);
                });
            }
        } catch (e) {
            console.error("Error loading filters", e);
        }
    }

    async function loadUsersData() {
        const search = userSearch.value;
        const lic = filterLicense.value;
        const grp = filterGroup.value;

        // Build query params
        let url = `/api/users?page=${currentPage}&limit=${limit}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        if (lic) url += `&license=${encodeURIComponent(lic)}`;
        if (grp) url += `&group=${encodeURIComponent(grp)}`;

        // Dynamic update of Excel Export link
        let exportUrl = `/api/export`;
        // Even if we export all, we can append filters if needed in the future,
        // for now let's just let it download the latest full snapshot.
        exportExcelBtn.href = exportUrl;

        try {
            usersTableBody.innerHTML = '<tr><td colspan="6" class="text-center">Загрузка данных...</td></tr>';
            
            const res = await fetch(url);
            if (!res.ok) throw new Error("Не удалось загрузить список пользователей.");
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
        }, 4000); // 400ms debounce
    });
    
    // Immediate load on pressing enter in search
    userSearch.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            clearTimeout(searchTimeout);
            currentPage = 1;
            loadUsersData();
        }
    });

    filterLicense.addEventListener("change", () => {
        currentPage = 1;
        loadUsersData();
    });

    filterGroup.addEventListener("change", () => {
        currentPage = 1;
        loadUsersData();
    });

    resetFiltersBtn.addEventListener("click", () => {
        userSearch.value = "";
        filterLicense.value = "";
        filterGroup.value = "";
        currentPage = 1;
        loadUsersData();
    });

    // 3. Sync Tab
    const syncsTableBody = document.getElementById("syncs-table-body");
    const triggerSyncBtn = document.getElementById("trigger-sync-btn");
    const quickSyncBtn = document.getElementById("quick-sync-btn");

    async function loadSyncSessions() {
        try {
            const res = await fetch("/api/syncs");
            if (!res.ok) throw new Error("Не удалось загрузить сессии синхронизации.");
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

    async function startSync() {
        try {
            triggerSyncBtn.disabled = true;
            quickSyncBtn.disabled = true;
            
            const res = await fetch("/api/sync", { method: "POST" });
            const data = await res.json();
            
            if (!res.ok) throw new Error(data.detail || "Не удалось запустить синхронизацию.");

            showToast(data.message, "success");
            
            // Poll sync sessions list every 5 seconds while sync is running
            if (syncIntervalId) clearInterval(syncIntervalId);
            syncIntervalId = setInterval(async () => {
                const activeTab = document.querySelector(".nav-item.active").getAttribute("data-tab");
                
                // Fetch sync history to see if it finished
                const checkRes = await fetch("/api/syncs");
                if (checkRes.ok) {
                    const syncs = await checkRes.json();
                    const latest = syncs[0];
                    if (latest && latest.status !== "running") {
                        clearInterval(syncIntervalId);
                        triggerSyncBtn.disabled = false;
                        quickSyncBtn.disabled = false;
                        showToast(latest.status === "success" ? "Синхронизация завершена успешно!" : "Синхронизация завершилась с ошибкой.", latest.status === "success" ? "success" : "error");
                        
                        // Reload current tab content
                        if (activeTab === "dashboard") loadDashboardData();
                        if (activeTab === "users") loadUsersData();
                        if (activeTab === "sync") loadSyncSessions();
                    }
                }
                
                if (activeTab === "sync") {
                    loadSyncSessions();
                }
            }, 5000);

        } catch (error) {
            showToast(error.message, "error");
            triggerSyncBtn.disabled = false;
            quickSyncBtn.disabled = false;
        }
    }

    triggerSyncBtn.addEventListener("click", startSync);
    quickSyncBtn.addEventListener("click", startSync);

    // 4. Settings Tab
    const settingsForm = document.getElementById("settings-form");

    async function loadSettings() {
        try {
            const res = await fetch("/api/config");
            if (!res.ok) throw new Error("Не удалось загрузить конфигурацию.");
            const data = await res.json();

            if (data) {
                document.getElementById("tenant_id").value = data.tenant_id || "";
                document.getElementById("client_id").value = data.client_id || "";
                document.getElementById("client_secret").value = data.client_secret || "";
                document.getElementById("email_to").value = data.email_to || "";
                
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
    loadDashboardData();
    loadFilters();
});
