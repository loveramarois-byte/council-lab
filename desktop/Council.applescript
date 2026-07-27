on run
	set appPath to POSIX path of (path to me)
	set bundledLauncher to appPath & "Contents/Resources/launcher/start-council.sh"
	if (do shell script "test -x " & quoted form of bundledLauncher & "; echo $?") is "0" then
		do shell script "/usr/bin/nohup /bin/zsh " & quoted form of bundledLauncher & " >/dev/null 2>&1 &"
		return
	end if

	set projectPathFile to appPath & "Contents/Resources/project-path.txt"
	try
		set projectDirectory to do shell script "/bin/cat " & quoted form of projectPathFile
	on error
		display dialog "启动器缺少项目路径。请重新双击“安装 Council.command”。" buttons {"好"} with title "Council 无法启动"
		return
	end try

	set launcher to projectDirectory & "/desktop/start-council.sh"
	if (do shell script "test -x " & quoted form of launcher & "; echo $?") is not "0" then
		display dialog "项目文件夹已被移动或删除。请在当前位置重新双击“安装 Council.command”。" buttons {"好"} with title "Council 无法启动"
		return
	end if

	do shell script "/usr/bin/nohup /bin/zsh " & quoted form of launcher & " >/dev/null 2>&1 &"
end run
