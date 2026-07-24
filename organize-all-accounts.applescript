-- Organize INBOX across ALL Mail.app accounts. MOVE only — never delete.
-- Folders: Action Waiting Meetings IT Releases Security FYI Personal Archive
-- Run: osascript organize-all-accounts.applescript

on classify(subj)
	set s to subj as string
	considering case
		-- false for contains; use ignoring case below
	end considering
	ignoring case
		if s contains "leaked secrets" or s contains "phishing" or s contains "security alert" or s contains "infosec" then return "Security"
		if s contains "Accepted:" or s contains "Declined:" or s contains "Canceled:" or s contains "New Time Proposed" or s contains "Invitation:" or s contains "Webex meeting" then return "Meetings"
		if s contains "ITSUPPORT-" or s contains "IT Notification" or s contains "Egnyte" or s contains "SharePoint" or s contains "Planned Maintenance" then return "IT"
		if s contains "WINT" or s contains "CROWD_" or s contains "Internal release" or s contains "Release " then return "Releases"
		if s contains "weekly update" or s contains "Birthday" or s contains "newsletter" or s contains "Welcome To" or s contains "API token" or s contains "New sign-in" or s contains "Your receipt" or s contains "order confirmation" or s contains "promotion" or s contains "shipping" or s contains "DocuSign" or s contains "Looking for new role" or s contains "startup" then return "FYI"
		if s contains "Missing Property" or s contains "action required" or s contains "can we deploy" then return "Action"
	end ignoring
	return ""
end classify

on ensureFolder(acct, fname)
	try
		mailbox fname of acct
	on error
		try
			make new mailbox with properties {name:fname} at end of acct
		end try
	end try
end ensureFolder

on inboxOf(acct)
	try
		return mailbox "INBOX" of acct
	end try
	try
		return mailbox "Inbox" of acct
	end try
	return missing value
end inboxOf

tell application "Mail"
	set folderNames to {"Action", "Waiting", "Meetings", "IT", "Releases", "Security", "FYI", "Personal", "Archive"}
	set report to ""
	repeat with acct in accounts
		set uname to user name of acct
		repeat with fname in folderNames
			my ensureFolder(acct, fname as string)
		end repeat
		set inboxBox to my inboxOf(acct)
		if inboxBox is missing value then
			set report to report & "NO_INBOX " & uname & linefeed
		else
			set moved to 0
			set scanned to 0
			try
				set msgs to messages of inboxBox
				set n to count of msgs
				-- Cap per account so we don't hang Mail.app forever
				if n > 150 then set n to 150
				repeat with i from 1 to n
					set scanned to scanned + 1
					try
						set m to item i of msgs
						set subj to subject of m
						set destName to my classify(subj)
						if destName is not "" then
							set destBox to mailbox destName of acct
							move m to destBox
							set moved to moved + 1
						end if
					end try
				end repeat
			end try
			set report to report & "ORG " & uname & " moved=" & moved & " scanned=" & scanned & linefeed
		end if
	end repeat
	return report
end tell
