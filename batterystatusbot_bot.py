async def check_grid_status(app):
    """Точна перевірка наявності світла виключно за показниками зовнішньої мережі."""
    global grid_state
    monitor_sid = STATION_ID_1
    
    while True:
        try:
            data = get_station_data(monitor_sid)
            if data:
                grid_power = float(data.get("gridPower") or 0)
                purchase_power = float(data.get("purchasePower") or 0)
                soc = data.get("batterySOC")
                
                logger.info(
                    f"Grid Check [Station {monitor_sid}] -> "
                    f"gridPower: {grid_power}W | purchasePower: {purchase_power}W | SOC: {soc}%"
                )
                
                # Мережа є ТІЛЬКИ якщо є потік енергії З МЕРЕЖІ (gridPower або purchasePower > 0)
                # Ігноруємо wirePower, бо вона живиться від батарей при вимкненні світла!
                is_currently_online = (grid_power > 0 or purchase_power > 0)
                
                if grid_state["is_online"] and not is_currently_online:
                    # Світло ЗНИКЛО
                    grid_state["is_online"] = False
                    grid_state["outage_start"] = asyncio.get_event_loop().time()
                    
                    if NOTIFY_CHAT_ID:
                        text = (
                            f"🔴 <b>Світло зникло в будинку!</b>\n"
                            f"Мережева потужність: <b>0 Вт</b>\n"
                            f"Заряд батареї: <b>{soc}%</b>"
                        )
                        await app.bot.send_message(
                            int(NOTIFY_CHAT_ID), text, message_thread_id=THREAD_ID, parse_mode="HTML"
                        )
                        
                elif not grid_state["is_online"] and is_currently_online:
                    # Світло З'ЯВИЛОСЯ
                    grid_state["is_online"] = True
                    
                    duration_str = ""
                    if grid_state["outage_start"]:
                        duration_sec = asyncio.get_event_loop().time() - grid_state["outage_start"]
                        hours = int(duration_sec // 3600)
                        minutes = int((duration_sec % 3600) // 60)
                        duration_str = f"\n⏱ Було вимкнено: <b>{hours} год {minutes} хв</b>"
                    
                    if NOTIFY_CHAT_ID:
                        text = (
                            f"🟢 <b>Світло з'явилося!</b>"
                            f"{duration_str}\n"
                            f"Потужність мережі: <b>{max(grid_power, purchase_power)} Вт</b>"
                        )
                        await app.bot.send_message(
                            int(NOTIFY_CHAT_ID), text, message_thread_id=THREAD_ID, parse_mode="HTML"
                        )
        except Exception as e:
            logger.error(f"Grid check exception: {e}")
        
        await asyncio.sleep(120)
