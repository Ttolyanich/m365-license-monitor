<#
.SYNOPSIS
    Экспорт пользователей Microsoft 365, их лицензий и групп в CSV-отчет с отправкой по почте.
.DESCRIPTION
    Скрипт подключается к Microsoft Graph API с помощью Client ID, Client Secret и Tenant ID.
    Оптимизирован для крупных тенантов путем кэширования SKU (лицензий) и членства в группах в памяти.
    После сбора отправляет CSV файл на указанный почтовый ящик.
.PARAMETER TenantId
    ID тенанта Microsoft 365 (Directory ID).
.PARAMETER ClientId
    ID зарегистрированного приложения (Application ID).
.PARAMETER ClientSecret
    Секрет зарегистрированного приложения (Client Secret).
.PARAMETER EmailTo
    Адрес получателя отчета.
.PARAMETER EmailFrom
    Адрес отправителя отчета.
.PARAMETER SmtpServer
    SMTP сервер для отправки почты.
.PARAMETER SmtpPort
    Порт SMTP сервера (по умолчанию 587).
.PARAMETER UseSmtpAuth
    Использовать ли аутентификацию для SMTP.
.PARAMETER SmtpUser
    Имя пользователя SMTP.
.PARAMETER SmtpPassword
    Пароль SMTP.
.PARAMETER SendViaGraph
    Отправлять письмо через MS Graph API вместо SMTP (требуется разрешение Mail.Send).
.PARAMETER SendFromGraphUser
    UPN или ID пользователя Graph, от имени которого отправлять письмо.
#>

param (
    [Parameter(Mandatory = $true)]
    [string]$TenantId,

    [Parameter(Mandatory = $true)]
    [string]$ClientId,

    [Parameter(Mandatory = $true)]
    [string]$ClientSecret,

    [Parameter(Mandatory = $true)]
    [string]$EmailTo,

    [Parameter(Mandatory = $true)]
    [string]$EmailFrom,

    [Parameter(Mandatory = $false)]
    [string]$SmtpServer,

    [Parameter(Mandatory = $false)]
    [int]$SmtpPort = 587,

    [Parameter(Mandatory = $false)]
    [switch]$UseSmtpAuth,

    [Parameter(Mandatory = $false)]
    [string]$SmtpUser,

    [Parameter(Mandatory = $false)]
    [string]$SmtpPassword,

    [Parameter(Mandatory = $false)]
    [switch]$SendViaGraph,

    [Parameter(Mandatory = $false)]
    [string]$SendFromGraphUser
)

$ErrorActionPreference = "Stop"

# 1. Проверка и установка модуля Microsoft.Graph
Write-Host "Проверка модуля Microsoft.Graph..." -ForegroundColor Cyan
if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Users)) {
    Write-Host "Модуль Microsoft.Graph не найден. Установка..." -ForegroundColor Yellow
    Install-Module Microsoft.Graph -Scope CurrentUser -Force -AllowClobber
}

Import-Module Microsoft.Graph.Authentication
Import-Module Microsoft.Graph.Users
Import-Module Microsoft.Graph.Groups
Import-Module Microsoft.Graph.Identity.DirectoryManagement

# 2. Подключение к Microsoft Graph
Write-Host "Подключение к Microsoft Graph..." -ForegroundColor Cyan
$SecSecret = ConvertTo-SecureString $ClientSecret -AsPlainText -Force
$Credential = New-Object System.Management.Automation.PSCredential($ClientId, $SecSecret)
$GraphConnection = Connect-MgGraph -TenantId $TenantId -ClientId $ClientId -ClientSecretCredential $Credential -NoWelcome

if (-not $GraphConnection) {
    throw "Не удалось подключиться к Microsoft Graph."
}

# 3. Кэширование SKU (Лицензий)
Write-Host "Загрузка информации о лицензиях (SKU)..." -ForegroundColor Cyan
$skuMap = @{}
try {
    $skus = Get-MgSubscribedSku -All
    foreach ($sku in $skus) {
        $skuMap[$sku.SkuId.ToString()] = $sku.SkuPartNumber
    }
} catch {
    Write-Warning "Не удалось получить список SKU. В отчете будут отображаться GUID лицензий."
}

# 4. Сбор информации о группах и их участниках (оптимизированный кэш)
Write-Host "Загрузка информации о группах..." -ForegroundColor Cyan
$groupMap = @{} # UserId -> List of GroupNames
try {
    $groups = Get-MgGroup -All -Property Id, DisplayName
    $totalGroups = $groups.Count
    $counter = 0

    foreach ($group in $groups) {
        $counter++
        if ($counter % 50 -eq 0 -or $counter -eq $totalGroups) {
            Write-Host "Обработано групп: $counter из $totalGroups" -ForegroundColor Gray
        }

        try {
            $members = Get-MgGroupMember -GroupId $group.Id -All -ErrorAction SilentlyContinue
            foreach ($member in $members) {
                $memberId = $member.Id
                if (-not $groupMap.ContainsKey($memberId)) {
                    $groupMap[$memberId] = [System.Collections.Generic.List[string]]::new()
                }
                [void]$groupMap[$memberId].Add($group.DisplayName)
            }
        } catch {
            # Пропускаем группы, к которым нет доступа
        }
    }
} catch {
    Write-Warning "Не удалось получить список групп или их участников."
}

# 5. Загрузка всех пользователей
Write-Host "Загрузка списка пользователей..." -ForegroundColor Cyan
$users = Get-MgUser -All -Property Id, UserPrincipalName, DisplayName, Mail, AccountEnabled, AssignedLicenses

# 6. Формирование отчета
Write-Host "Формирование отчета..." -ForegroundColor Cyan
$report = [System.Collections.Generic.List[PSObject]]::new()

foreach ($user in $users) {
    $userLicenses = @()
    if ($user.AssignedLicenses) {
        foreach ($lic in $user.AssignedLicenses) {
            $skuId = $lic.SkuId.ToString()
            if ($skuMap.ContainsKey($skuId)) {
                $userLicenses += $skuMap[$skuId]
            } else {
                $userLicenses += $skuId
            }
        }
    }

    $userGroups = @()
    if ($groupMap.ContainsKey($user.Id)) {
        $userGroups = $groupMap[$user.Id].ToArray()
    }

    $report.Add([PSCustomObject]@{
        Id                = $user.Id
        UserPrincipalName = $user.UserPrincipalName
        DisplayName       = $user.DisplayName
        Mail              = $user.Mail
        AccountEnabled    = $user.AccountEnabled
        Licenses          = $userLicenses -join "; "
        Groups            = $userGroups -join "; "
    })
}

# 7. Экспорт в CSV
$csvPath = Join-Path $env:TEMP "M365_Users_Licenses_Report.csv"
Write-Host "Экспорт отчета в $csvPath..." -ForegroundColor Cyan
$report | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8

# 8. Отправка отчета по почте
$subject = "Отчет по лицензиям и группам M365 от $(Get-Date -Format 'dd.MM.yyyy HH:mm')"
$body = @"
Добрый день!

Во вложении находится актуальный отчет по пользователям, их лицензиям и группам в Microsoft 365.
Всего выгружено пользователей: $($report.Count).

Сгенерировано автоматически.
"@

if ($SendViaGraph) {
    if (-not $SendFromGraphUser) {
        throw "Параметр SendFromGraphUser обязателен при отправке через Graph API."
    }
    Write-Host "Отправка почты через Microsoft Graph API от имени $SendFromGraphUser..." -ForegroundColor Cyan
    
    $attachmentBytes = [System.IO.File]::ReadAllBytes($csvPath)
    $attachmentBase64 = [System.Convert]::ToBase64String($attachmentBytes)
    
    $params = @{
        Message = @{
            Subject = $subject
            Body = @{
                ContentType = "Text"
                Content = $body
            }
            ToRecipients = @(
                @{
                    EmailAddress = @{
                        Address = $EmailTo
                    }
                }
            )
            Attachments = @(
                @{
                    "@odata.type" = "#microsoft.graph.fileAttachment"
                    Name = "M365_Users_Licenses_Report.csv"
                    ContentType = "text/csv"
                    ContentBytes = $attachmentBase64
                }
            )
        }
        SaveToSentItems = $true
    }
    
    Send-MgUserMail -UserId $SendFromGraphUser -BodyParameter $params
} else {
    Write-Host "Отправка почты через SMTP сервер $SmtpServer..." -ForegroundColor Cyan
    $smtpParams = @{
        To = $EmailTo
        From = $EmailFrom
        Subject = $subject
        Body = $body
        SmtpServer = $SmtpServer
        Port = $SmtpPort
        Attachments = $csvPath
        Encoding = [System.Text.Encoding]::UTF8
    }
    
    if ($UseSmtpAuth) {
        $secPassword = ConvertTo-SecureString $SmtpPassword -AsPlainText -Force
        $cred = New-Object System.Management.Automation.PSCredential($SmtpUser, $secPassword)
        $smtpParams["Credential"] = $cred
        $smtpParams["UseSsl"] = $true
    }
    
    Send-MailMessage @smtpParams
}

# 9. Очистка временного файла
if (Test-Path $csvPath) {
    Remove-Item $csvPath -Force
}

# Отключение от Graph
Disconnect-MgGraph | Out-Null
Write-Host "Готово! Отчет успешно отправлен." -ForegroundColor Green
