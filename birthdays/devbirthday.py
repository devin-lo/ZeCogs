# Red-Discordbot Cog: Birthdays
# VERSION 2.0.3 (aka DevBirthday)
# Based on the birthdays cog originally by ZeLarpMaster#0818 on Discord
# Published on July 16, 2018
# 
# This cog is intended for use with Red-Discordbot V2.
# 
# Changelog:
# V2 (July 4, 2018) Original release.
# V2.0.1 (July 5, 2018) Add error message when embed messages can't be sent due to incorrect server permissions.
# V2.0.2 (July 11, 2018) Added character limit checks.
# V2.0.3 (July 16, 2018) Added enable/disable feature, added clarifying text to bday set command, fixed the check for bday role setting.
# 
# Features added from original cog:
# 
# 1. Added terms of use command. The terms of use can be read from a text file, in the data folder for this cog.
# 2. Rewrote bday set command, such that you must acknowledge the terms of use to prevent legal repercussions, based on the check_answer code from the trivia cog. Now also shows the year in the confirmation message if given.
# 3. Added usernames to command prompts for clarity and ease of use.
# 4. Added a command to view birthday settings for a server.
# 5. Added cleaning function to automatically remove birthday settings for a server, if the bot is no longer in the server, somewhat based on clean_bday code.
# 6. Added manual remove birthday setting commands for a server, mod-only commands.
# 7. Added manual cleaning command, owner-only, just in case it's necessary (this cog is not good at cleaning up its own garbage data from the configuration file).
# 8. Added text to distinguish whether someone's birthday has occurred already or not in the birthday list, if the age is provided.
# 9. Added functionality for valid leap year birthdays (February 29) to be added to the database, viewed on the list, and to be announced either on the actual date or on February 28 (if not currently in a leap year).
# 10. Rewrote birthday list code to only show registered users that are part of the server that the command is run on. Also added functionality in DM to show the singular user's birthday if run.
# 11. Added methods to check if bot has no permissions to send messages to the announcement channel or manage server for role-giving, in order to help the end-user make the bot function on their server
# 12. Added character limit checks and ways to avoid erroring the cog due to exceeded character limit, especially for the birthday list. This includes limiting the year input to being between -9999 and 9999.
# 13. Added an enable/disable feature for cog, in case a server owner wishes to opt-out of the service entirely for their server.


import asyncio
import discord
import os.path
import os
import datetime
import time
import itertools
import contextlib
import calendar
import math

from discord.ext import commands
from .utils import checks
from .utils.dataIO import dataIO

class Birthdays:
    """Announces people's birthdays and gives them a birthday role for the whole UTC day"""

    # File related constants
    DATA_FOLDER = "data/birthdays"
    CONFIG_FILE_PATH = DATA_FOLDER + "/config.json"

    # Configuration default
    CONFIG_DEFAULT = {
        "roles": {},  # {server.id: role.id} of the birthday roles
        "channels": {},  # {server.id: channel.id} of the birthday announcement channels
        "birthdays": {},  # {date: {user.id: year}} of the users' birthdays
        "yesterday": [],  # List of user ids who's birthday was done yesterday
        "disable" : []  # List of servers where the birthday cog is disabled. Cog is enabled by default
    }

    # Message constants
    ROLE_SET = ":white_check_mark: The birthday role on **{s}** has been set to: **{r}**."
    CHANNEL_SET = ":white_check_mark: The channel for announcing birthdays on **{s}** has been set to: <#{c}>."
    BDAY_REMOVED = ":put_litter_in_its_place: **{}**, your birthday has been removed."
    B_SET_INTRO = "**{a}, to use this command, you must agree to the Terms of Use**, which are provided using {p}bday termsofuse.\n\nTo continue, please acknowledge that you have read and agree to the Terms of Use by typing \"yes\". Otherwise, type \"no\" to abort this command."

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.check_configs()
        self.load_data()
        self.bday_loop = asyncio.ensure_future(self.initialise())  # Starts a loop which checks daily for birthdays
        self.bdayinputsesh = []

    # Events
    async def initialise(self):
        await self.bot.wait_until_ready()
        with contextlib.suppress(RuntimeError):
            while self == self.bot.get_cog(self.__class__.__name__):  # Stops the loop when the cog is reloaded
                now = datetime.datetime.utcnow()
                tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                await asyncio.sleep((tomorrow - now).total_seconds())
                self.clean_yesterday_bdays()
                self.clean_bdays()
                self.clean_settings()
                self.do_today_bdays()
                self.save_data()

    def __unload(self):
        self.bday_loop.cancel()  # Forcefully cancel the loop when unloaded

    # Commands
    @commands.group(pass_context=True, invoke_without_command=True)
    async def bday(self, ctx):
        """Birthday Announcement Bot\nBy using this bot function, you agree to the Terms of Use."""
        await self.bot.send_cmd_help(ctx)

    @bday.command(name="channel", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_channel(self, ctx, channel: discord.Channel):
        """Mod Command. Sets the birthday announcement channel for this server (no function in DM)"""
        message = ctx.message
        c = message.channel
        server = message.server
        if server.id not in self.config["disable"]:
            if channel.type == discord.ChannelType.text:
                self.config["channels"][server.id] = channel.id
                self.save_data()
                msg = self.CHANNEL_SET.format(s=server.name, c=channel.id)
                if server.me.permissions_in(channel).send_messages:
                    await self.bot.send_message(c, msg)
                else:
                    msg += "\nDon't forget to allow the bot to send messages in that channel for the announcement function to work!"
                    await self.bot.send_message(c, msg)
            else:
                await self.bot.say("You cannot set a voice channel to be the birthday announcement channel.")

    @bday.command(name="remchannel", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_remchannel(self, ctx):
        """Mod Command. Removes the birthday announcement channel for this server (no function in DM)"""
        message = ctx.message
        c = message.channel
        server = message.server
        self.remove_setting(server.id, "channels")
        self.save_data()
        self.clean_settings()
        self.save_data()
        await self.bot.say("The setting for the birthday announcement channel for **{}** has been removed.".format(server.name))

    @bday.command(name="role", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_role(self, ctx, role: discord.Role):
        """Mod Command. Sets the birthday role for this server (no function in DM). When setting this, the role must be in quotation marks."""
        message = ctx.message
        channel = message.channel
        server = message.server
        if server.id not in self.config["disable"]:
            self.config["roles"][server.id] = role.id
            self.save_data()
            msg = self.ROLE_SET.format(s=server.name, r=role.name)
            if channel.permissions_for(server.me).manage_roles and server.me.top_role > role:
                await self.bot.send_message(channel, msg)
            else:
                msg += "\nPlease note that you need to give the bot a role with the Manage Roles permission that is higher in the role hierarchy than the birthday role for this feature to work."
                await self.bot.send_message(channel, msg)

    @bday.command(name="remrole", pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def bday_remrole(self, ctx):
        """Mod Command. Removes the birthday role for this server (no function in DM)"""
        message = ctx.message
        c = message.channel
        server = message.server
        self.remove_setting(server.id, "roles")
        self.save_data()
        self.clean_settings()
        self.save_data()
        await self.bot.say("The setting for the birthday role for **{}** has been removed.".format(server.name))

    @bday.command(name="remove", aliases=["del", "clear", "rm"], pass_context=True)
    async def bday_remove(self, ctx):
        """Removes your birthday from the stored list"""
        message = ctx.message
        channel = message.channel
        author = message.author
        self.remove_user_bday(author.id)
        self.save_data()
        self.clean_bdays()
        self.save_data()
        await self.bot.send_message(channel, self.BDAY_REMOVED.format(author.name))

    @bday.command(name="set", pass_context=True)
    async def bday_set(self, ctx):
        """Sets your birthday date. Please read the Terms of Use before using this command"""
        message = ctx.message
        channel = message.channel
        author = message.author
        server = message.server
        if server.id not in self.config["disable"]:
            session = self.get_bdayinput_by_user(message.author)
            if not session: # NOTE: This is based on the code for trivia, as that was the most accessible example of this bot awaiting for further inputs.
                await self.bot.send_message(channel, self.B_SET_INTRO.format(a=author.name, p=ctx.prefix))
                t = BDayInputSession(self.bot, message)
                self.bdayinputsesh.append(t)
                await t.confirmtheterms()
            else:
                await self.bot.say("**{}**, you're already trying to input your birthday.".format(author.name))
        else:
            await self.bot.say(":x: Birthday announcement service is disabled in this server.")
        
    @bday.command(name="list", pass_context=True)
    async def bday_list(self, ctx):
        """Lists the birthdays. If a user has their year set, it will display the age they'll get after their birthday this year."""
        message = ctx.message
        channel = message.channel
        server = message.server
        self.clean_bdays()
        self.save_data()
        bdays = self.config["birthdays"]
        this_year = datetime.date.today().year
        this_day = datetime.date.today()
        new_day = this_day.replace(year=4)
        embed = discord.Embed(title="Birthday List", color=discord.Colour.lighter_grey())
        fieldsadded = 0
        mustPM = False
        if server is not None: # if not DM
            if server.id not in self.config["disable"]:
                for k, g in itertools.groupby(sorted(datetime.datetime.fromordinal(int(o)) for o in bdays.keys()),
                                              lambda i: i.month):
                    # Basically separates days with "\n" and people on the same day with ", "
                    value = "" # Because we would not like to list users that are not part of the server, the embed value MUST be built up iteratively from an empty string.
                    for date in g:
                        if len(bdays.get(str(date.toordinal()))) > 0:
                            valhead = date.strftime("%d").lstrip("0") + ": "
                            valfoot = ""
                            # Separating the day number and user_id/year parts into valhead and valfoot
                            # allows us to throw away the header part if there are no users on that day in the subject server (i.e. value would be empty),
                            # but lets us keep days separated by "\n" and people separated by ", " as needed
                            for u_id, year in bdays.get(str(date.toordinal()), {}).items():
                                if server.get_member(u_id) is not None:
                                    valfoot += "<@{}>".format(u_id) + ("" if year is None else " (turns {})".format(this_year - int(year)) if new_day.toordinal() < date.toordinal() else " (turned {})".format(this_year - int(year))) + ", "
                            if valfoot is not "":
                                value += valhead + valfoot.rstrip(", ") + "\n"
                    value = value.rstrip() # Due to the fact that value has to be built up, there will be an extra line at the end that must be eliminated, same for comma separator in the line above
                    if value is not "":  # value is empty if there are no birthdays in that month for the subject server
                        if len(value) > 1024: # field value overflowing is still manageable by splitting it across more fields, as long as we don't exceed 25.
                            stillSplicing = True
                            firstTime = True
                            while stillSplicing:
                                if value[0:1024].rfind("\n") > 0: # splicing by day
                                    splice = value[0:1024].rfind("\n")
                                    if firstTime:
                                        embed.add_field(name=datetime.datetime(year=4, month=k, day=1).strftime("%B"), value=value[0:splice])
                                        firstTime = False
                                    else:
                                        embed.add_field(name=datetime.datetime(year=4, month=k, day=1).strftime("%B") + " (cont'd)", value=value[0:splice])
                                    value = value[splice+1:len(value)]
                                    fieldsadded = fieldsadded + 1
                                    if fieldsadded > 25:
                                        mustPM = True
                                        break
                                else: # too many users per day
                                    if value[0:1024].rfind(",") > 0: # splicing by user
                                        splice = value[0:1024].rfind(",")
                                        if firstTime:
                                            embed.add_field(name=datetime.datetime(year=4, month=k, day=1).strftime("%B"), value=value[0:splice])
                                            firstTime = False
                                        else:
                                            embed.add_field(name=datetime.datetime(year=4, month=k, day=1).strftime("%B") + " (cont'd)", value=value[0:splice])
                                        lefsplice = value.find(":") + 2
                                        value = value[0:lefsplice] + value[splice+2:len(value)]
                                        fieldsadded = fieldsadded + 1
                                        if fieldsadded > 25:
                                            mustPM = True
                                            break
                                    else: # (should not happen)
                                        mustPM = True
                                        break
                                if len(value) <= 1024:
                                    stillSplicing = False
                                    embed.add_field(name=datetime.datetime(year=4, month=k, day=1).strftime("%B") + " (cont'd)", value=value)
                                    fieldsadded = fieldsadded + 1
                                    if fieldsadded > 25:
                                        mustPM = True
                                        break
                        else:
                            embed.add_field(name=datetime.datetime(year=4, month=k, day=1).strftime("%B"), value=value)
                            fieldsadded = fieldsadded + 1
                            if fieldsadded > 25:
                                mustPM = True
                                break
                    if fieldsadded > 25:
                        mustPM = True
                        break
                
                if fieldsadded <= 25:
                    try:
                        await self.bot.send_message(channel, embed=embed)
                    except (discord.Forbidden, discord.HTTPException):
                        await self.bot.send_message(channel, ":x: I can't display the list here because the server admin has not enabled embed links in this channel. Try another channel, or let them know they need to fix this!\nIf the problem is still not fixed please contact the developer.")
                else:
                    await self.bot.send_message(channel, ":x: I can't display the birthday list for this server because it is too long. Users for this server can only see their own individual birthdays by using this command in DM.")
            else:
                await self.bot.say(":x: Birthday announcement service is disabled in this server.")
            
        else: # if command was used in DM: will only display the birthday of the subject user.
            author = message.author
            user_id = author.id
            found_id = False
            for k, v in bdays.items():
                if user_id in v:
                    month = datetime.datetime.fromordinal(int(k)).strftime("%B")
                    day = datetime.datetime.fromordinal(int(k)).strftime("%d").lstrip("0")
                    msg = "**{a}**, your birthday was recorded as: **{m} {d}".format(a=author.name, m = month, d = day)
                    year = list(v.values())[list(v.keys()).index(user_id)]
                    if year is not None:
                        msg += ", {}**.".format(year)
                    else:
                        msg += "**."
                    found_id = True
                    await self.bot.say(msg)
            if not found_id:
                await self.bot.say("You have not set a birthday.")

    @bday.command(name="settings", pass_context=True, no_pm=True)
    async def bday_settings(self, ctx):
        """Lists the server settings for channel and role (no function in DM)"""
        message = ctx.message
        channel = message.channel
        server = message.server
        self.clean_settings()
        self.save_data()
        embed = discord.Embed(title="Birthday Bot Server Settings for {}".format(server), color=discord.Colour.dark_teal())
        if server.id in self.config["disable"]:
            embed.add_field(name="Cog Status", value="Disabled")
        try:
            thechannel = self.config["channels"][server.id]
        except KeyError:
            embed.add_field(name="Announcement Channel", value="No channel set")
        else:
            if server.me.permissions_in(server.get_channel(thechannel)).send_messages:
                embed.add_field(name="Announcement Channel", value="<#" + thechannel + ">")
            else:
                embed.add_field(name="Announcement Channel", value="<#" + thechannel + ">\n\nBot lacks permissions to\nspeak in the specified\nchannel")
        try:
            therole = self.config["roles"][server.id]
        except KeyError:
            embed.add_field(name="Birthday Role", value="No role set")
        else:
            rolename = discord.utils.find(lambda r: r.id == therole, server.roles)
            if channel.permissions_for(server.me).manage_roles and server.me.top_role > rolename:
                embed.add_field(name="Birthday Role", value=rolename.name)
            else:
                embed.add_field(name="Birthday Role", value=rolename.name + "\n\nBot lacks permissions to\ngive users this role")
        try:
            await self.bot.send_message(channel, embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            await self.bot.send_message(channel, ":x: I can't display the settings list here because the server admin has not enabled embed links in this channel. Try another channel, or let them know they need to fix this!\nIf the problem is still not fixed please contact the developer.")
    
    @bday.command(name="termsofuse", pass_context=True)
    async def bday_termsofuse(self, ctx):
        """Provides the Terms of Use for using the Birthday function"""
        path = "data/birthdays/termsofuse.txt" # this file and the filepath can be modified as needed

        with open(path, "rb") as f:
            try:
                encoding = chardet.detect(f.read())["encoding"]
            except:
                encoding = "ISO-8859-1"
        
        msg = ""
        testcases = ["\n", ".", ",", "!", "?"]
        
        with open(path, "r", encoding=encoding) as f:
            for line in f:
                msg += str(line).format(ctx.prefix)
        
        while len(msg) > 2000:
            notBroken = True
            for t in testcases:
                if msg[0:2000].rfind(t) > 0:
                    index = msg[0:2000].rfind(t)
                    if t == "\n":
                        await self.bot.say(msg[0:index])
                    else:
                        await self.bot.say(msg[0:index+1])
                    msg = msg[index+1:len(msg)]
                    notBroken = False
                    break
            if notBroken:
                await self.bot.say(msg[0:1999] + "-")
                msg = msg[1999:len(msg)]        
        
        await self.bot.say(msg)
    
    @bday.command(name="disable", pass_context=True, no_pm=True)
    @checks.serverowner_or_permissions(administrator=True)
    async def bday_disable(self, ctx):
        """Server administrator only: disable birthday announcement cog in server. (Cog is enabled by default)"""
        message = ctx.message
        channel = message.channel
        server = message.server
        diservers = self.config["disable"]
        if server.id not in diservers:
            self.config["disable"].append(server.id)
            self.save_data()
            await self.bot.say(":white_check_mark: Birthday announcement service is now disabled for this server.")
        else:
            await self.bot.say("Birthday announcements are already disabled for this server.")
    
    @bday.command(name="enable", pass_context=True, no_pm=True)
    @checks.serverowner_or_permissions(administrator=True)
    async def bday_enable(self, ctx):
        """Server administrator only: enable birthday announcement cog in server. (Cog is enabled by default)"""
        message = ctx.message
        channel = message.channel
        server = message.server
        diservers = self.config["disable"]
        if server.id in diservers:
            self.config["disable"].remove(server.id)
            self.save_data()
            await self.bot.say(":white_check_mark: Birthday announcement service is now enabled for this server.")
        else:
            await self.bot.say("Birthday announcements are already enabled for this server.")
    
    @bday.command(name="clean", pass_context=True, no_pm=True)
    @checks.is_owner()
    async def bday_clean(self):
        """Bot owner command only. Manually clean data if not already completed automatically"""
        self.clean_bdays()
        self.clean_settings()
        self.save_data()
        await self.bot.say(":put_litter_in_its_place: Data successfully cleared.")
    
    # Utilities
    async def clean_bday(self, user_id): # This command is used to take off the birthday role from users whose birthday has passed.
        for server_id, role_id in self.config["roles"].items():
            server = self.bot.get_server(server_id)
            if server is not None:
                role = discord.utils.find(lambda r: r.id == role_id, server.roles)
                # If discord.Server.roles was an OrderedDict instead...
                member = server.get_member(user_id)
                if member is not None and role is not None and role in member.roles:
                    # If the user and the role are still on the server and the user has the bday role
                    await self.bot.remove_roles(member, role)
    
    def clean_bdays(self):
        """Cleans the birthday entries with no user's birthday
        Also removes birthdays of users who aren't in any visible server anymore

        Happens when someone changes their birthday and there's nobody else in the same day"""
        birthdays = self.config["birthdays"]
        for date, bdays in birthdays.copy().items():
            for user_id, year in bdays.copy().items():
                if not any(s.get_member(user_id) is not None for s in self.bot.servers):
                    del birthdays[date][user_id]
            if len(bdays) == 0:
                del birthdays[date]
    
    def clean_settings(self):
        """Cleans the channel and role entries where the bot is no longer a member of a server, or if the channel or role is removed."""
        channels = self.config["channels"]
        for s, c in channels.copy().items():
            serv = discord.utils.find(lambda svr: svr.id == s, self.bot.servers)
            if serv is None:
                del channels[s]
            else:
                chan = discord.utils.find(lambda chn: chn.id == c, serv.channels)
                if chan is None:
                    del channels[s]
                
        roles = self.config["roles"]
        for s, r in roles.copy().items():
            serv = discord.utils.find(lambda svr: svr.id == s, self.bot.servers)
            if serv is None:
                del roles[s]
            else:
                rol = discord.utils.find(lambda rle: rle.id == r, serv.roles)
                if rol is None:
                    del roles[s]

    def remove_user_bday(self, user_id):
        for date, user_ids in self.config["birthdays"].items():
            if user_id in user_ids:
                del self.config["birthdays"][date][user_id]
        # Won't prevent the cleaning problem here cause the users can leave so we'd still want to clean anyway
    
    def remove_setting(self, servid, settingtype):
        setting = self.config[settingtype]
        for s, remitem in setting.copy().items():
            if servid in s:
                del self.config[settingtype][s]
    
    def clean_yesterday_bdays(self):
        for user_id in self.config["yesterday"]:
            asyncio.ensure_future(self.clean_bday(user_id))
        self.config["yesterday"].clear()

    def do_today_bdays(self):
        this_date = datetime.datetime.utcnow().date().replace(year=4)

        if not this_date.toordinal == 1155: # if today is not February 29
            for user_id, year in self.config["birthdays"].get(str(this_date.toordinal()), {}).items():
                asyncio.ensure_future(self.handle_bday(user_id, 1, year))

        if not calendar.isleap(datetime.date.today().year) and this_date.toordinal == 1154: # if it's not a leap year, and today is February 28
            for user_id, year in self.config["birthdays"].get(str(1155, {})).items():
                asyncio.ensure_future(self.handle_bday(user_id, 2, year))
        
        if this_date.toordinal == 1155: #if today is February 29 (also implied to be a leap year)
            for user_id, year in self.config["birthdays"].get(str(this_date.toordinal()), {}).items():
                asyncio.ensure_future(self.handle_bday(user_id, 3, year))

    async def handle_bday(self, user_id, flag, year):
        if flag == 1: # non leap day birthday
            if year is not None:
                age = datetime.date.today().year - int(year)  # Doesn't support non-western age counts but whatever. NOTE: I don't know what the original developer meant by this
                msg = "<@{}> is now **{} years old**! :tada:".format(user_id, age)
            else:
                msg = "It's <@{}>'s birthday today! :tada:".format(user_id)
        elif flag == 2: # leap day birthday on non-leap year
            if year is not None:
                age = datetime.date.today().year - int(year)
                leapage = self.calcLeapAge(year)
                msg = "Because it's not a leap year, today we will celebrate the birthday of <@{}> who turns **{} years old** or **{} leap years old**! :tada:".format(user_id, age, leapage)
            else:
                msg = "Because it's not a leap year, today we will celebrate the birthday of <@{}>! :tada:".format(user_id)
        else: # leap day birthday on leap year
            if year is not None:
                age = datetime.date.today().year - int(year)
                leapage = int(self.calcLeapAge(year))
                msg = "<@{}> is now **{} years old** or **{} leap years old**! :tada:".format(user_id, age, leapage)
            else:
                msg = "It's <@{}>'s birthday today! :tada:".format(user_id)
        
        for server_id, channel_id in self.config["channels"].items():
            server = self.bot.get_server(server_id)
            if server is not None:  # Ignore unavailable servers or servers the bot isn't in anymore
                member = server.get_member(user_id)
                if member is not None:
                    role_id = self.config["roles"].get(server_id)
                    if role_id is not None:
                        role = discord.utils.find(lambda r: r.id == role_id, server.roles)
                        if role is not None:
                            try:
                                await self.bot.add_roles(member, role)
                            except (discord.Forbidden, discord.HTTPException):
                                pass
                            else:
                                self.config["yesterday"].append(member.id)
                    channel = server.get_channel(channel_id)
                    if channel is not None:
                        try:
                            await self.bot.send_message(channel, msg)
                        except (discord.Forbidden, discord.HTTPException): # bot will error without a line to catch exception if it can't send msg to channel
                            pass
    
    def foundLeap(self, year, direction):
        foundtheLeap = False
        y = year

        while not foundtheLeap:
            y = y + direction * 1
            if calendar.isleap(y):
                foundtheLeap = True
        return y
    
    def calcLeapAge(self, year):
        this_year = datetime.date.today().year
        lower = self.foundLeap(this_year,-1)
        upper = self.foundLeap(lower,1)
        age = calendar.leapdays(year+1,this_year) + float(this_year - lower)/(upper - lower)
        return age

    def parse_date(self, date_str):
        result = None
        try:
            result = datetime.datetime.strptime(date_str + "-0004", "%m-%d-%Y")
        except ValueError:
            pass
        return result
    
    def get_bdayinput_by_user(self, author):
        for t in self.bdayinputsesh:
            if t.starter == author:
               return t
        return None
    
    async def on_writebday(self, instance, message, date, year):
        channel = message.channel
        author = message.author
        birthday = self.parse_date(date)
        self.remove_user_bday(author.id)
        self.config["birthdays"].setdefault(str(birthday.toordinal()), {})[author.id] = year
        self.save_data()
        bday_month_str = birthday.strftime("%B")
        bday_day_str = birthday.strftime("%d").lstrip("0")  # To remove the zero-capped
        msg = ":white_check_mark: **{a}**, your birthday has been set to: **{d}".format(a = author.name, d = bday_month_str + " " + bday_day_str)
        if year is not None:
            msg += ", {}**.".format(year)
        else:
            msg += "**."
        await self.bot.send_message(channel, msg)
        self.bot.dispatch("input_end", instance)
    
    async def on_message(self, message):
        if message.author != self.bot.user:
            session = self.get_bdayinput_by_user(message.author)
            if session:
                await session.check_answer(message)
    
    async def on_input_end(self, instance):
        if instance in self.bdayinputsesh:
            self.bdayinputsesh.remove(instance)
    
    # Config
    def check_configs(self):
        self.check_folders()
        self.check_files()

    def check_folders(self):
        if not os.path.exists(self.DATA_FOLDER):
            print("Creating data folder...")
            os.makedirs(self.DATA_FOLDER, exist_ok=True)

    def check_files(self):
        self.check_file(self.CONFIG_FILE_PATH, self.CONFIG_DEFAULT)

    def check_file(self, file, default):
        if not dataIO.is_valid_json(file):
            print("Creating empty " + file + "...")
            dataIO.save_json(file, default)

    def load_data(self):
        self.config = dataIO.load_json(self.CONFIG_FILE_PATH)

    def save_data(self):
        dataIO.save_json(self.CONFIG_FILE_PATH, self.config)


class BDayInputSession():
    # this is based on the code for trivia
    def __init__(self, bot, message):
        self.bot = bot
        self.channel = message.channel
        self.starter = message.author
        self.status = "waiting for terms confirm"
        self.timer = None
    
    async def confirmtheterms(self):
        self.timer = int(time.perf_counter())
        
        while self.status == "waiting for terms confirm":
            if abs(self.timer - int(time.perf_counter())) >= 45:
                await self.bot.say("**{}**, birthday input cancelled due to user inactivity. No information has been stored.".format(self.starter.name))            
                await self.stop_bdayinput()
                return True
            await asyncio.sleep(1) #Waiting for an answer or for the time limit
        
        if self.status == "confirmed terms":
            self.timer = None
            self.status = "waiting for birthday"
            self.timer = int(time.perf_counter())
            await self.bot.say("**{}**, please input your numeric birthday in the format of `M-D`\nYou may optionally add the year if desired using the following format: `M-D,Y`\nNOTE: do not do the command (`=bday set`) in front of your date input.".format(self.starter.name))
            while self.status == "waiting for birthday":
                if abs(self.timer - int(time.perf_counter())) >= 90:
                    await self.bot.say("**{}**, birthday input cancelled due to inactivity or failure to provide a valid birthday. No information has been stored.".format(self.starter.name))            
                    await self.stop_bdayinput()
                    return True
                await asyncio.sleep(1) #Waiting for an answer or for the time limit
        else:
            await self.bot.say("**{}**, birthday input process has been aborted. No information has been stored.".format(self.starter.name))
            await self.stop_bdayinput()
            return True
    
    
    async def check_answer(self, message):
        if message.author == self.starter:
            if self.status == "waiting for terms confirm":
                if message.content.lower() == "yes":
                    self.status = "confirmed terms"
                    return
                elif message.content.lower() == "no":
                    self.status = "abort"
                    return
                else:
                    return
            elif self.status == "waiting for birthday":
                year = None
                if "," in message.content:
                    date, year = message.content.split(",")
                    year = year.lstrip()
                else:
                    date = message.content
                birthday = self.parse_date(date)
                yr = self.check_year(year)
                if birthday is None or yr is False:
                    await self.bot.send_message(message.channel, ":x: **{}**, the birthday date you entered is invalid. It must be inputted as `M-D` or `M-D,Y`.".format(message.author.name))
                else:
                    if birthday.toordinal() == 1155 and year is not None:
                        try:
                            birthday.replace(year=int(year))
                        except ValueError:
                            await self.bot.send_message(message.channel, ":x: **{a}**, the birthday date you entered is invalid. {y} is not a leap year.".format(a=message.author.name,y=year))
                        else:
                            await self.send_bdayinput(message, date, year)
                    else:
                        await self.send_bdayinput(message, date, year)
                return
            else:
                await self.bot.send_message(message.channel, "**{}**, something unexpected has gone wrong here. Try again. No information has been stored.".format(message.author.name))
                await self.stop_bdayinput()
                return
        else:
            return

    def parse_date(self, date_str):
        result = None
        try:
            result = datetime.datetime.strptime(date_str + "-0004", "%m-%d-%Y")
        except ValueError:
            pass
        return result
    
    def check_year(self, year):
        result = False
        if year is None:
            return year
        elif int(year) >= -9999 or int(year) <= 9999:
                return year
        else:
            return result
    
    async def stop_bdayinput(self):
        self.status = "stop"
        self.bot.dispatch("input_end", self)        
    
    async def send_bdayinput(self, message, date, year):
        self.status = "bdayreceived"
        self.bot.dispatch("writebday", self, message, date, year)
    
def setup(bot):
    # Creating the cog
    cog = Birthdays(bot)
    # Finally, add the cog to the bot.
    bot.add_cog(cog)
