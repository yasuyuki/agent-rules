# Prove the Windows hosted-runner primitive before using it for native probes.
$ErrorActionPreference = 'Stop'
$name = 'nativee2e' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$secret = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
$password = ConvertTo-SecureString $secret -AsPlainText -Force
$root = Join-Path ($env:SystemDrive + '\') ('native-e2e-' + [Guid]::NewGuid().ToString('N'))
$controller = Join-Path $root 'controller'
$consumer = Join-Path $root 'consumer'
$identity = "$env:COMPUTERNAME\$name"
try {
    New-LocalUser -Name $name -Password $password -PasswordNeverExpires | Out-Null
    New-Item -ItemType Directory -Path $controller, $consumer -Force | Out-Null
    Set-Content -Path (Join-Path $controller 'expected.txt') -Value 'controller-only'
    $consumerAcl = Get-Acl $consumer
    $allow = New-Object Security.AccessControl.FileSystemAccessRule(
        $identity, 'Modify', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $consumerAcl.AddAccessRule($allow)
    Set-Acl -Path $consumer -AclObject $consumerAcl
    $controllerAcl = Get-Acl $controller
    $deny = New-Object Security.AccessControl.FileSystemAccessRule(
        $identity, 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Deny')
    $controllerAcl.AddAccessRule($deny)
    Set-Acl -Path $controller -AclObject $controllerAcl
    $credential = New-Object Management.Automation.PSCredential($identity, $password)

    $write = Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -Credential $credential `
        -WorkingDirectory $consumer -ArgumentList '/c echo child-wrote>proof.txt' `
        -Wait -PassThru -NoNewWindow
    if ($write.ExitCode -ne 0 -or -not (Test-Path (Join-Path $consumer 'proof.txt'))) {
        throw 'restricted user cannot write to consumer workspace'
    }
    $read = Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -Credential $credential `
        -WorkingDirectory $consumer -ArgumentList "/c type `"$(Join-Path $controller 'expected.txt')`" >nul 2>nul" `
        -Wait -PassThru -NoNewWindow
    if ($read.ExitCode -eq 0) {
        throw 'restricted user can read controller fixture'
    }
    Write-Output 'Windows native E2E user/ACL isolation primitive passed (no model call).'
}
finally {
    if (Get-LocalUser -Name $name -ErrorAction SilentlyContinue) {
        Remove-LocalUser -Name $name
    }
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
