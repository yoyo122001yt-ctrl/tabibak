def wait_time(patients, minutes_per_patient):
    total = patients * minutes_per_patient
    print("Patients waiting:", patients)
    print("Your wait time is:", total, "minutes")
    
    if total <= 30:
        print("✅ Great! Short wait time, go now!")
    elif total <= 60:
        print("⚠️ Moderate wait, you can head out soon.")
    else:
        print("❌ Long wait! Consider coming back later.")
    print("---")

wait_time(2, 15)
wait_time(4, 15)
wait_time(8, 15)