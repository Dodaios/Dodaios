package de.dodaios.mobile

import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/** Full-screen "Jarvis is calling" with accept (opens the voice call) and decline. */
class IncomingCallActivity : AppCompatActivity() {
    private lateinit var message: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (24 * resources.displayMetrics.density).toInt()
        val title = TextView(this).apply {
            setTextColor(getColor(R.color.hud_cyan))
            textSize = 22f
            letterSpacing = 0.2f
            gravity = Gravity.CENTER
            text = getString(R.string.incoming)
        }
        message = TextView(this).apply {
            setTextColor(getColor(R.color.hud_text))
            textSize = 16f
            gravity = Gravity.CENTER
            setPadding(0, pad, 0, pad)
        }
        val accept = Button(this).apply {
            text = getString(R.string.accept)
            setTextColor(getColor(R.color.hud_cyan))
            setBackgroundResource(R.drawable.hud_button)
            setOnClickListener {
                RingService.cancelIncoming(this@IncomingCallActivity)
                startActivity(Intent(this@IncomingCallActivity, CallActivity::class.java))
                finish()
            }
        }
        val decline = Button(this).apply {
            text = getString(R.string.decline)
            setTextColor(getColor(R.color.hud_gold))
            setBackgroundResource(R.drawable.hud_button)
            setOnClickListener {
                RingService.cancelIncoming(this@IncomingCallActivity)
                finish()
            }
        }
        val wide = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        setContentView(
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER_HORIZONTAL
                setBackgroundColor(getColor(R.color.hud_bg))
                setPadding(pad, pad * 2, pad, pad)
                addView(RingIndicatorView(context).apply { online = true }, LinearLayout.LayoutParams(pad * 6, pad * 6))
                addView(title)
                addView(message, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
                addView(accept, wide)
                addView(decline, LinearLayout.LayoutParams(wide).apply { topMargin = pad / 2 })
            },
        )
        show(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        show(intent)
    }

    private fun show(intent: Intent) {
        message.text = intent.getStringExtra(RingService.EXTRA_TEXT).orEmpty()
    }
}
